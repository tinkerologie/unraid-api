"""Async GraphQL client for Unraid server."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
import warnings
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

import aiohttp

from unraid_api.capabilities import ServerCapabilities, build_introspection_query
from unraid_api.exceptions import (
    UnraidAPIError,
    UnraidAuthenticationError,
    UnraidConnectionError,
    UnraidSSLError,
    UnraidTimeoutError,
)

if TYPE_CHECKING:
    import ssl
    from collections.abc import AsyncGenerator
    from types import TracebackType

    from unraid_api.models import (
        ApiKey,
        ArrayDisk,
        ArraySubscriptionUpdate,
        Cloud,
        Connect,
        ContainerUpdateStatus,
        CpuMetrics,
        CpuTelemetryMetrics,
        DisplaySettings,
        DockerContainer,
        DockerContainerLogs,
        DockerContainerStats,
        DockerNetwork,
        DockerPortConflicts,
        Flash,
        InfoNetworkInterface,
        LogFile,
        MemoryMetrics,
        Network,
        NetworkMetrics,
        Notification,
        NotificationOverview,
        Owner,
        ParityCheck,
        ParityHistoryEntry,
        PhysicalDisk,
        Plugin,
        PluginInstallEvent,
        PluginInstallOperation,
        Registration,
        RemoteAccess,
        ResolvedOrganizerV1,
        Server,
        ServerInfo,
        Service,
        Settings,
        Share,
        SystemMetrics,
        SystemTime,
        TemperatureMetrics,
        TimeZoneOption,
        UnraidArray,
        UPSConfiguration,
        UPSDevice,
        UserAccount,
        Vars,
        VersionInfo,
        VmDomain,
    )


_LOGGER = logging.getLogger(__name__)

# HTTP status codes
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
DEFAULT_HTTP_PORT = 80
DEFAULT_HTTPS_PORT = 443


class UnraidClient:
    """Async client for interacting with Unraid GraphQL API.

    This client handles:
    - SSL/TLS mode detection (No, Yes, Strict)
    - Automatic redirect discovery for myunraid.net
    - Session management with proper cleanup
    - GraphQL query and mutation execution

    Example:
        async with UnraidClient("192.168.1.100", "your-api-key") as client:
            if await client.test_connection():
                info = await client.get_system_info()

    """

    def __init__(
        self,
        host: str,
        api_key: str,
        *,
        http_port: int = DEFAULT_HTTP_PORT,
        https_port: int = DEFAULT_HTTPS_PORT,
        verify_ssl: bool = True,
        timeout: int = 30,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            host: Server hostname or IP (with or without http:// or https://).
            api_key: Unraid API key with ADMIN role.
            http_port: HTTP port for redirect discovery (default 80).
            https_port: HTTPS port (default 443).
            verify_ssl: Whether to verify SSL certificates (default True).
            timeout: Request timeout in seconds (default 30s).
            session: Optional aiohttp session (for HA websession injection).

        """
        self.host = self._strip_userinfo(host.strip())
        if not (1 <= http_port <= 65535):
            raise ValueError(f"http_port must be between 1 and 65535, got {http_port}")
        if not (1 <= https_port <= 65535):
            raise ValueError(
                f"https_port must be between 1 and 65535, got {https_port}"
            )
        if timeout < 1:
            raise ValueError(f"timeout must be >= 1 second, got {timeout}")
        self.http_port = http_port
        self.https_port = https_port
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._auth_headers: dict[str, str] = {"x-api-key": api_key}
        self._session: aiohttp.ClientSession | None = session
        self._owns_session: bool = session is None
        self._resolved_url: str | None = None
        self._capabilities: ServerCapabilities | None = None
        self._capabilities_lock: asyncio.Lock = asyncio.Lock()

    def __repr__(self) -> str:
        """Safe repr that never exposes the API key."""
        return (
            f"UnraidClient(host={self._sanitize_host_for_log()!r}, "
            f"port={self.https_port}, verify_ssl={self.verify_ssl})"
        )

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Get the aiohttp session."""
        return self._session

    async def __aenter__(self) -> UnraidClient:
        """Async context manager entry."""
        await self._create_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    async def _create_session(self) -> None:
        """Create aiohttp session with proper SSL configuration."""
        if self._session is not None:
            return

        ssl_context: ssl.SSLContext | bool | None = None
        if not self.verify_ssl:
            ssl_context = False
            _LOGGER.warning(
                "SSL verification disabled for %s. "
                "Connection is encrypted but server identity is not verified.",
                self._sanitize_host_for_log(),
            )
        else:
            ssl_context = True

        connector_kwargs: dict[str, Any] = {
            "ssl": ssl_context,
            "force_close": False,
            "limit": 10,
            "limit_per_host": 5,
        }
        # enable_cleanup_closed was fixed in CPython 3.14 and is a no-op there
        if sys.version_info < (3, 14):
            connector_kwargs["enable_cleanup_closed"] = True
        connector = aiohttp.TCPConnector(**connector_kwargs)
        timeout_config = aiohttp.ClientTimeout(
            total=self.timeout,
            connect=min(10, self.timeout),
            sock_connect=min(10, self.timeout),
            sock_read=self.timeout,
        )

        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout_config,
        )
        self._owns_session = True

    async def close(self) -> None:
        """Close the aiohttp session if we created it."""
        if self._session is not None and self._owns_session:
            try:
                await self._session.close()
                # Allow underlying connections to close cleanly
                await asyncio.sleep(0)
            except Exception:
                _LOGGER.debug("Error closing session", exc_info=True)
            self._session = None

    @staticmethod
    def _strip_userinfo(host: str) -> str:
        """Strip any embedded credentials (user:pass@) from the host value.

        Ensures that self.host never carries sensitive userinfo, eliminating
        the risk of logging credentials downstream.
        """
        if "://" in host:
            parsed = urlparse(host)
            if parsed.username or parsed.password:
                netloc = parsed.hostname or ""
                if parsed.port:
                    netloc += f":{parsed.port}"
                host = parsed._replace(netloc=netloc).geturl()
        elif "@" in host:
            host = host.split("@", 1)[1]
        return host

    def _sanitize_host_for_log(self) -> str:
        """Get a sanitized host string safe for logging (no credentials or secrets).

        This method is ONLY for logging purposes and may return placeholder strings
        like "<redacted-host>". Never use this for URL construction.
        """
        raw_host = (self.host or "").strip()
        if not raw_host:
            return "<redacted-host>"

        # If this looks like a URL, sanitize it first, then extract host[:port]
        if "://" in raw_host:
            sanitized = self._sanitize_url(raw_host)
            if sanitized in ("<invalid-url>", "<redacted>"):
                return "<redacted-host>"
            try:
                parsed = urlparse(sanitized)
            except Exception:
                return "<redacted-host>"
            hostname = parsed.hostname or ""
            if not hostname:
                return "<redacted-host>"
            host = f"{hostname}:{parsed.port}" if parsed.port else hostname
        else:
            # Non-URL host: strip any userinfo (user:pass@) if present
            host = raw_host
            if "@" in host:
                host = host.split("@", 1)[1]

        host = host.rstrip("/")

        # As a final safeguard, avoid logging values that look like secrets.
        # Long token without dots/colons is likely not a hostname.
        if host and len(host) >= 24 and all(ch not in host for ch in (".", ":", "/")):
            return "<redacted-host>"

        # Additional safeguards: only log strings that look like a normal host[:port].
        # - Reject values with whitespace or control characters.
        # - Reject very long values that are unlikely to be hostnames.
        # - Reject values where most characters are not typical hostname characters.
        if any(ch.isspace() for ch in host):
            return "<redacted-host>"

        if len(host) > 255:
            # Longer than any reasonable hostname/IP representation.
            return "<redacted-host>"

        # Keep letters, digits, dot, dash, colon and brackets (for IPv6).
        safe_chars = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-[]"
        )
        safe_count = sum(1 for ch in host if ch in safe_chars)
        # If fewer than 70% of characters are "host-like", assume it may be a secret.
        if safe_count == 0 or safe_count / len(host) < 0.7:
            return "<redacted-host>"

        return host or "<redacted-host>"

    def _normalize_host_for_request(self) -> str:
        """Normalize and validate the host for actual network requests.

        This method MUST return a valid, routable hostname or IP address.
        Never returns placeholder strings like "<redacted-host>".

        Returns:
            str: A valid hostname or IP address suitable for URL construction.

        Raises:
            UnraidConnectionError: If the host is invalid or cannot be normalized.
        """
        raw_host = (self.host or "").strip()
        if not raw_host:
            raise UnraidConnectionError("Host cannot be empty")

        # If this looks like a URL, extract the hostname
        if "://" in raw_host:
            try:
                parsed = urlparse(raw_host)
                hostname = parsed.hostname
                if not hostname:
                    raise UnraidConnectionError(
                        f"Could not extract hostname from URL: {raw_host}"
                    )
                # Preserve port from URL if present
                if parsed.port:
                    return f"{hostname}:{parsed.port}"
                return hostname
            except Exception as e:
                raise UnraidConnectionError(
                    f"Invalid host URL format: {raw_host}"
                ) from e

        # Non-URL host: strip any userinfo (user:pass@) if present
        host = raw_host
        if "@" in host:
            host = host.split("@", 1)[1]

        host = host.rstrip("/")

        # Basic validation: ensure it's not empty after normalization
        if not host:
            raise UnraidConnectionError("Host cannot be empty after normalization")

        # Reject hosts with whitespace (likely invalid)
        if any(ch.isspace() for ch in host):
            raise UnraidConnectionError(
                "Host contains whitespace characters, which is invalid"
            )

        # Reject unreasonably long hostnames
        if len(host) > 255:
            raise UnraidConnectionError("Host exceeds maximum length of 255 characters")

        return host

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Remove credentials and sensitive components from URL for logging."""
        try:
            parsed = urlparse(url)
        except Exception:
            # If parsing fails, avoid logging the raw value
            return "<invalid-url>"

        hostname = parsed.hostname or ""
        port = parsed.port
        if not hostname:
            # No usable host component; avoid emitting potentially sensitive data
            return "<redacted>"

        netloc = hostname
        if port:
            netloc += f":{port}"

        # Drop username, password, query parameters and fragment entirely
        sanitized = parsed._replace(
            netloc=netloc,
            path=parsed.path or "",
            params="",
            query="",
            fragment="",
        )
        return sanitized.geturl()

    async def _discover_redirect_url(self) -> tuple[str | None, bool]:
        """Discover the correct URL and SSL mode for the Unraid server.

        Unraid servers have three SSL/TLS modes:
        - No: HTTP only, no redirect
        - Yes: HTTP redirects to HTTPS (self-signed certificate)
        - Strict: HTTP redirects to myunraid.net (valid certificate)

        Returns:
            Tuple of (redirect_url, use_ssl):
            - (myunraid_url, True) for Strict mode
            - (https_url, True) for Yes mode
            - (None, False) for No mode (HTTP works directly)
            - (None, True) if HTTP check fails (fallback to HTTPS)

        """
        if self._session is None:
            await self._create_session()

        if self._session is None:
            raise UnraidConnectionError("Failed to create HTTP session")

        # Get validated host for URL construction
        request_host = self._normalize_host_for_request()

        # Short-circuit: if http_port == https_port, assume this port is configured
        # to serve HTTPS and skip the plain HTTP probe to avoid a likely 400 from nginx.
        if self.http_port == self.https_port:
            _LOGGER.debug(
                "http_port == https_port (%d), assuming HTTPS for %s",
                self.http_port,
                self._sanitize_host_for_log(),
            )
            return (None, True)

        http_port_suffix = (
            "" if self.http_port == DEFAULT_HTTP_PORT else f":{self.http_port}"
        )

        http_url = f"http://{request_host}{http_port_suffix}/graphql"
        _LOGGER.debug("Checking for redirect at %s", self._sanitize_url(http_url))

        # Get sanitized host for logging
        clean_host = self._sanitize_host_for_log()

        try:
            async with self._session.get(http_url, allow_redirects=False) as response:
                _LOGGER.debug("HTTP response status: %d", response.status)

                if response.status in (301, 302, 307, 308):
                    redirect_url = response.headers.get("Location")
                    _LOGGER.debug(
                        "Redirect location: %s",
                        self._sanitize_url(redirect_url) if redirect_url else None,
                    )
                    if redirect_url:
                        parsed = urlparse(redirect_url)
                        hostname = parsed.hostname

                        # Check for myunraid.net redirect (Strict mode)
                        if hostname and (
                            hostname == "myunraid.net"
                            or hostname.endswith(".myunraid.net")
                        ):
                            # Normalize to strip query params and fragments
                            normalized_strict = urlunparse(
                                (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
                            )
                            _LOGGER.info(
                                "Discovered myunraid.net redirect (Strict mode): %s",
                                normalized_strict,
                            )
                            return (normalized_strict, True)

                        # Check for HTTPS redirect (Yes mode)
                        if parsed.scheme == "https":
                            # Security: only follow HTTPS redirects to the same
                            # host as the configured server.  Redirects to a
                            # different hostname are rejected to prevent SSRF
                            # and API-key theft via redirect manipulation.
                            #
                            # Use urlparse to extract the bare hostname so that
                            # IPv6 addresses (e.g. [::1]:8080) are handled
                            # correctly — a plain split(":")[0] would break on
                            # bracketed IPv6 notation.
                            configured_parsed = urlparse(f"http://{request_host}")
                            configured_hostname = configured_parsed.hostname
                            if not configured_hostname:
                                # Cannot extract configured hostname; reject redirect
                                # to avoid bypassing the SSRF check.
                                _LOGGER.warning(
                                    "Could not extract hostname from %s; "
                                    "HTTPS redirect rejected.",
                                    self._sanitize_host_for_log(),
                                )
                                return (None, False)
                            if hostname and hostname != configured_hostname:
                                _LOGGER.warning(
                                    "HTTPS redirect to different host rejected "
                                    "(possible SSRF): redirect=%s",
                                    self._sanitize_url(redirect_url),
                                )
                                return (None, False)
                            port = parsed.port
                            if port == DEFAULT_HTTPS_PORT:
                                normalized = f"https://{hostname}{parsed.path}"
                            else:
                                # Normalize to strip query params and fragments
                                normalized = urlunparse(
                                    (
                                        parsed.scheme,
                                        parsed.netloc,
                                        parsed.path,
                                        "",
                                        "",
                                        "",
                                    )
                                )
                            _LOGGER.info(
                                "Discovered HTTPS redirect (Yes mode): %s",
                                normalized,
                            )
                            return (normalized, True)

                # Detect nginx returning 400 when plain HTTP hits an HTTPS port
                if response.status == 400:
                    # Read only enough bytes to detect the nginx message,
                    # avoiding unbounded memory use on large error bodies.
                    raw = await response.content.read(512)
                    body = raw.decode("utf-8", errors="ignore")
                    if "the plain http request was sent to https port" in body.lower():
                        if self.http_port == DEFAULT_HTTPS_PORT:
                            https_url = f"https://{clean_host}/graphql"
                        else:
                            https_url = f"https://{clean_host}:{self.http_port}/graphql"
                        _LOGGER.info(
                            "HTTP probe got 400 'plain HTTP to HTTPS port' from %s, "
                            "server requires HTTPS at %s",
                            clean_host,
                            https_url,
                        )
                        return (https_url, True)

                # HTTP endpoint is accessible (SSL/TLS mode is "No")
                _LOGGER.info(
                    "HTTP endpoint accessible (status %d), SSL/TLS mode is 'No' for %s",
                    response.status,
                    clean_host,
                )
                return (None, False)

        except TimeoutError as err:
            if self.http_port != DEFAULT_HTTP_PORT:
                msg = (
                    f"Timeout connecting to {clean_host}"
                    f" on port {self.http_port}: {err}"
                )
                raise UnraidTimeoutError(msg) from err
            _LOGGER.debug("HTTP check timed out, will try HTTPS: %s", err)
        except aiohttp.ClientError as err:
            # When the user specified a custom (non-default) HTTP port and
            # that port is unreachable, raise immediately — don't silently
            # fall back to HTTPS on a different port.  See GitHub issue #9.
            if self.http_port != DEFAULT_HTTP_PORT:
                raise UnraidConnectionError(
                    f"Cannot connect to {clean_host} on port {self.http_port}: {err}"
                ) from err

            _LOGGER.debug("HTTP check failed, will try HTTPS: %s", err)

        return (None, True)

    async def _make_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Make a GraphQL request to the Unraid server.

        Args:
            payload: GraphQL query/mutation payload.

        Returns:
            Response data dictionary.

        Raises:
            UnraidConnectionError: On network errors.
            UnraidAuthenticationError: On authentication failures.
            UnraidTimeoutError: On request timeout.

        """
        if self._session is None:
            await self._create_session()

        if self._session is None:
            raise UnraidConnectionError("Failed to create HTTP session")

        if self._resolved_url is None:
            redirect_url, use_ssl = await self._discover_redirect_url()
            if redirect_url:
                self._resolved_url = redirect_url
            else:
                request_host = self._normalize_host_for_request()
                if use_ssl:
                    protocol = "https"
                    port_suffix = (
                        f":{self.https_port}"
                        if self.https_port != DEFAULT_HTTPS_PORT
                        else ""
                    )
                else:
                    protocol = "http"
                    port_suffix = (
                        f":{self.http_port}"
                        if self.http_port != DEFAULT_HTTP_PORT
                        else ""
                    )
                self._resolved_url = f"{protocol}://{request_host}{port_suffix}/graphql"
            _LOGGER.debug("Using URL: %s", self._sanitize_url(self._resolved_url))

        url = self._resolved_url

        try:
            async with self._session.post(
                url, json=payload, headers=self._auth_headers, allow_redirects=False
            ) as response:
                # Follow redirects if needed
                if response.status in (301, 302, 307, 308):
                    redirect_url = response.headers.get("Location")
                    if redirect_url:
                        parsed_original = urlparse(url)
                        parsed_redirect = urlparse(redirect_url)
                        redirect_host = parsed_redirect.hostname
                        original_host = parsed_original.hostname
                        # Only follow redirects to the same host or trusted myunraid.net
                        if redirect_host != original_host and not (
                            redirect_host is not None
                            and (
                                redirect_host == "myunraid.net"
                                or redirect_host.endswith(".myunraid.net")
                            )
                        ):
                            raise UnraidConnectionError(
                                f"Redirect to untrusted host rejected: "
                                f"{self._sanitize_url(redirect_url)}"
                            )
                        self._resolved_url = redirect_url
                        async with self._session.post(
                            redirect_url,
                            json=payload,
                            headers=self._auth_headers,
                            allow_redirects=False,
                        ) as redirect_response:
                            redirect_response.raise_for_status()
                            result: dict[str, Any] = await redirect_response.json()
                            return result
                    raise UnraidConnectionError(
                        f"Redirect {response.status} without Location header"
                    )

                if response.status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                    raise UnraidAuthenticationError(
                        "Invalid API key or insufficient permissions"
                    )

                response.raise_for_status()
                json_result: dict[str, Any] = await response.json()
                return json_result

        except UnraidAuthenticationError:
            raise
        except TimeoutError as err:
            raise UnraidTimeoutError(f"Request timed out: {err}") from err
        except aiohttp.ClientSSLError as err:
            raise UnraidSSLError(f"SSL certificate verification failed: {err}") from err
        except aiohttp.ClientResponseError as err:
            if err.status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                raise UnraidAuthenticationError(
                    "Invalid API key or insufficient permissions"
                ) from err
            # For server errors (5xx), avoid exposing internal server details
            if err.status >= 500:
                raise UnraidAPIError(f"HTTP error {err.status}") from err
            raise UnraidAPIError(f"HTTP error {err.status}: {err.message}") from err
        except aiohttp.ClientError as err:
            raise UnraidConnectionError(f"Connection failed: {err}") from err

    async def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL query.

        Args:
            query: GraphQL query string.
            variables: Optional query variables.

        Returns:
            Query response data (the 'data' field from GraphQL response).

        Raises:
            UnraidAPIError: On GraphQL errors with no data.
            UnraidConnectionError: On network errors.
            UnraidAuthenticationError: On authentication failures.

        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await self._make_request(payload)
        data = response.get("data", {})

        if "errors" in response:
            errors = response["errors"]
            error_messages = []
            for err in errors:
                if isinstance(err, dict):
                    msg = err.get("message", str(err))
                    path = err.get("path")
                    if path:
                        msg = f"{msg} (path: {path})"
                    error_messages.append(msg)
                else:
                    error_messages.append(str(err))

            _LOGGER.debug("GraphQL returned %d error(s)", len(errors))

            if data:
                # Partial failure - log and return data
                _LOGGER.debug(
                    "Some optional features unavailable: %s",
                    "; ".join(error_messages),
                )
            else:
                # Complete failure - raise exception
                _LOGGER.debug(
                    "GraphQL query returned no data with %d error(s): %s",
                    len(errors),
                    "; ".join(error_messages),
                )
                raise UnraidAPIError(
                    "GraphQL query failed",
                    errors=errors,
                )

        return dict(data)

    async def mutate(
        self, mutation: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL mutation.

        Args:
            mutation: GraphQL mutation string.
            variables: Optional mutation variables.

        Returns:
            Mutation response data.

        Raises:
            UnraidAPIError: On GraphQL errors.
            UnraidConnectionError: On network errors.

        """
        return await self.query(mutation, variables)

    async def get_capabilities(self) -> ServerCapabilities:
        """Return cached server capabilities, running introspection if needed.

        Uses a single aliased `__type` query to discover which fields the
        server supports, then caches the result for the lifetime of the
        client. If introspection fails (disabled, permission, or network
        error), falls back to permissive capabilities so queries are not
        blocked — the existing error-response path still catches real
        failures.
        """
        if self._capabilities is not None:
            return self._capabilities
        async with self._capabilities_lock:
            if self._capabilities is not None:
                return self._capabilities
            try:
                response = await self.query(build_introspection_query())
            except UnraidAuthenticationError:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "Capability introspection failed (%s); falling back to permissive",
                    err,
                )
                self._capabilities = ServerCapabilities.permissive()
                return self._capabilities
            self._capabilities = ServerCapabilities.from_introspection_response(
                response
            )
            return self._capabilities

    def _require_capability(self, feature: str, path: str) -> None:
        """Raise UnraidAPIError when a required capability is missing.

        Safe to call only after `get_capabilities()` has populated the cache;
        typical callers do `await self.get_capabilities()` first.
        """
        caps = self._capabilities
        if caps is None or caps.has(path):
            return
        raise UnraidAPIError(
            f"{feature} is not available on this Unraid server "
            f"(missing {path}). Update the Unraid API plugin to enable it."
        )

    def _get_ws_url(self) -> str:
        """Derive WebSocket URL from the resolved HTTP URL.

        Returns:
            WebSocket URL (ws:// or wss://).

        Raises:
            UnraidConnectionError: If the HTTP URL has not been resolved yet.

        """
        if self._resolved_url is None:
            raise UnraidConnectionError(
                "HTTP URL not resolved yet. Call a query or test_connection first."
            )
        url = self._resolved_url
        if url.startswith("https://"):
            return "wss://" + url[len("https://") :]
        if url.startswith("http://"):
            return "ws://" + url[len("http://") :]
        return url

    async def _ensure_resolved_url(self) -> None:
        """Ensure the HTTP URL is resolved (session + redirect discovery)."""
        if self._session is None:
            await self._create_session()
        if self._session is None:
            raise UnraidConnectionError("Failed to create HTTP session")
        if self._resolved_url is None:
            redirect_url, use_ssl = await self._discover_redirect_url()
            if redirect_url:
                self._resolved_url = redirect_url
            else:
                request_host = self._normalize_host_for_request()
                if use_ssl:
                    protocol = "https"
                    port_suffix = (
                        f":{self.https_port}"
                        if self.https_port != DEFAULT_HTTPS_PORT
                        else ""
                    )
                else:
                    protocol = "http"
                    port_suffix = (
                        f":{self.http_port}"
                        if self.http_port != DEFAULT_HTTP_PORT
                        else ""
                    )
                self._resolved_url = f"{protocol}://{request_host}{port_suffix}/graphql"

    @property
    def _ws_receive_timeout(self) -> int:
        """Seconds a subscription WebSocket may wait for a message."""
        return self.timeout * 10

    async def _ws_connect_and_init(
        self,
        ws_url: str,
        headers: dict[str, str],
    ) -> aiohttp.ClientWebSocketResponse:
        """Open a WebSocket and perform the graphql-transport-ws handshake."""
        if self._session is None:
            raise UnraidConnectionError("Session not initialized")
        try:
            ws = await self._session.ws_connect(
                ws_url,
                protocols=["graphql-transport-ws"],
                headers=headers,
                max_msg_size=16 * 1024 * 1024,
                receive_timeout=self._ws_receive_timeout,
            )
        except TimeoutError as err:
            raise UnraidTimeoutError(f"WebSocket connection timed out: {err}") from err
        except aiohttp.ClientSSLError as err:
            raise UnraidSSLError("SSL certificate verification failed") from err
        except aiohttp.ClientError as err:
            raise UnraidConnectionError(f"WebSocket connection failed: {err}") from err

        # Close the socket if the handshake fails; subscribe() only owns it
        # once this method returns.
        try:
            # --- connection_init ---
            await ws.send_str(
                json.dumps(
                    {
                        "type": "connection_init",
                        "payload": headers,
                    }
                )
            )

            # --- wait for connection_ack ---
            try:
                ack_msg = await ws.receive()
            except TimeoutError as err:
                raise UnraidTimeoutError(
                    f"No connection_ack received within {self._ws_receive_timeout}s"
                ) from err
            if ack_msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                raise UnraidConnectionError(
                    "WebSocket closed during connection_init handshake"
                )
            if ack_msg.type == aiohttp.WSMsgType.ERROR:
                raise UnraidConnectionError(
                    f"WebSocket error during handshake: {ws.exception()}"
                )
            ack_data = json.loads(ack_msg.data)
            if ack_data.get("type") != "connection_ack":
                msg_type = ack_data.get("type", "unknown")
                if msg_type == "connection_error":
                    payload = ack_data.get("payload", {})
                    raise UnraidAuthenticationError(f"Connection rejected: {payload}")
                raise UnraidConnectionError(f"Expected connection_ack, got: {msg_type}")
        except BaseException:
            try:
                await ws.close()
            except Exception:
                _LOGGER.debug("Error closing WebSocket after handshake", exc_info=True)
            raise
        return ws

    async def subscribe(
        self,
        subscription: str,
        variables: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a GraphQL subscription over WebSocket.

        Uses the ``graphql-transport-ws`` protocol. The returned async
        generator yields each ``next`` payload's ``data`` dict. The
        generator cleans up the WebSocket connection when exhausted or
        when the caller breaks out of the iteration.

        Args:
            subscription: GraphQL subscription query string.
            variables: Optional subscription variables.

        Yields:
            Response data dictionaries for each subscription event.

        Raises:
            UnraidConnectionError: On WebSocket connection or protocol errors.
            UnraidAuthenticationError: On authentication failures.
            UnraidTimeoutError: On connection or ``connection_ack`` timeout, or
                when no message arrives for ``timeout * 10`` seconds while
                streaming. Callers are expected to reconnect.

        Example::

            async for stats in client.subscribe(
                'subscription { dockerContainerStats { id cpuPercent } }'
            ):
                print(stats)

        """
        await self._ensure_resolved_url()
        if self._session is None:  # pragma: no cover
            err_msg = "Session not initialized"
            raise UnraidConnectionError(err_msg)

        ws_url = self._get_ws_url()
        sub_id = uuid.uuid4().hex[:8]

        ws: aiohttp.ClientWebSocketResponse | None = None
        try:
            ws = await self._ws_connect_and_init(ws_url, self._auth_headers)

            # --- subscribe ---
            subscribe_payload: dict[str, Any] = {"query": subscription}
            if variables:
                subscribe_payload["variables"] = variables

            await ws.send_str(
                json.dumps(
                    {
                        "id": sub_id,
                        "type": "subscribe",
                        "payload": subscribe_payload,
                    }
                )
            )

            # --- receive loop ---
            while True:
                try:
                    msg = await ws.receive()
                except TimeoutError as err:
                    raise UnraidTimeoutError(
                        "No message received on subscription for "
                        f"{self._ws_receive_timeout}s"
                    ) from err

                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "next":
                        payload = data.get("payload", {})
                        if "errors" in payload and "data" not in payload:
                            errors = payload["errors"]
                            error_msgs = [e.get("message", str(e)) for e in errors]
                            raise UnraidAPIError(
                                f"Subscription error: {'; '.join(error_msgs)}",
                                errors=errors,
                            )
                        yield payload.get("data") or {}

                    elif msg_type == "error":
                        errors = data.get("payload", [])
                        error_msgs = [e.get("message", str(e)) for e in errors]
                        raise UnraidAPIError(
                            f"Subscription error: {'; '.join(error_msgs)}",
                            errors=errors,
                        )

                    elif msg_type == "complete":
                        return

                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    return

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise UnraidConnectionError(f"WebSocket error: {ws.exception()}")

        finally:
            if ws is not None and not ws.closed:
                # Tell the server we're done with this subscription
                try:
                    await ws.send_str(json.dumps({"id": sub_id, "type": "complete"}))
                except Exception:
                    _LOGGER.debug("Error sending complete message", exc_info=True)
                await ws.close()

    # =========================================================================
    # Connection & Info Methods
    # =========================================================================

    async def test_connection(self) -> bool:
        """Test connection to Unraid server.

        Returns:
            True if connection successful.

        Raises:
            UnraidConnectionError: On connection failure.

        """
        result = await self.query("query { online }")
        return bool(result.get("online", False))

    async def check_compatibility(self) -> VersionInfo:
        """Check server version compatibility.

        Fetches the server version and verifies it meets minimum requirements.

        Returns:
            VersionInfo model with version details.

        Raises:
            UnraidVersionError: If the server version is below minimum requirements.

        """
        from packaging.version import InvalidVersion, Version

        from unraid_api.const import MIN_API_VERSION, MIN_UNRAID_VERSION
        from unraid_api.exceptions import UnraidVersionError

        version_info = await self.get_version()

        try:
            if Version(version_info.api) < Version(MIN_API_VERSION):
                raise UnraidVersionError(
                    f"API version {version_info.api} is below minimum "
                    f"required version {MIN_API_VERSION}"
                )
        except InvalidVersion:
            _LOGGER.warning("Could not parse API version: %s", version_info.api)

        try:
            if Version(version_info.unraid) < Version(MIN_UNRAID_VERSION):
                raise UnraidVersionError(
                    f"Unraid version {version_info.unraid} is below minimum "
                    f"required version {MIN_UNRAID_VERSION}"
                )
        except InvalidVersion:
            _LOGGER.warning("Could not parse Unraid version: %s", version_info.unraid)

        return version_info

    async def get_version(self) -> VersionInfo:
        """Get Unraid server version information.

        Returns:
            VersionInfo model with 'unraid' and 'api' version strings.

        """
        from unraid_api.models import VersionInfo

        query_str = """
            query {
                info {
                    versions {
                        core {
                            unraid
                            api
                        }
                    }
                }
            }
        """
        result = await self.query(query_str)
        versions = result.get("info", {}).get("versions", {}).get("core", {})
        return VersionInfo(
            unraid=versions.get("unraid") or "unknown",
            api=versions.get("api") or "unknown",
        )

    async def get_server_info(self) -> ServerInfo:
        """Get server information for device registration.

        Returns comprehensive server identification data useful for
        Home Assistant device registration and identification.

        Returns:
            ServerInfo model with all server identification data.

        """
        from unraid_api.models import ServerInfo

        query_str = """
            query {
                info {
                    system { uuid manufacturer model serial }
                    baseboard { manufacturer model serial }
                    os { hostname distro release kernel arch }
                    cpu { manufacturer brand cores threads }
                    versions { core { unraid api } }
                }
                server { lanip localurl remoteurl }
                registration { type state }
            }
        """
        result = await self.query(query_str)
        return ServerInfo.from_response(result)

    async def get_system_metrics(self) -> SystemMetrics:
        """Get system metrics for monitoring.

        Returns CPU, memory, swap, and uptime metrics for Home Assistant
        sensor entities. This is called every 30 seconds by the HA integration.

        Returns:
            SystemMetrics model with all metrics data.

        """
        from unraid_api.models import SystemMetrics

        query_str = """
            query {
                metrics {
                    cpu { percentTotal }
                    memory {
                        total used free available active buffcache
                        percentTotal
                        swapTotal swapUsed swapFree percentSwapTotal
                    }
                    temperature {
                        id
                        summary {
                            average
                            hottest { name current { value unit } }
                            coolest { name current { value unit } }
                            warningCount
                            criticalCount
                        }
                        sensors {
                            id name type location
                            current { value unit status }
                            min { value unit }
                            max { value unit }
                            warning critical
                        }
                    }
                }
                info {
                    os { uptime }
                    cpu { packages { temp totalPower } }
                }
            }
        """
        result = await self.query(query_str)
        return SystemMetrics.from_response(result)

    async def get_system_metrics_safe(self) -> SystemMetrics:
        """Get system metrics WITHOUT temperature sensors.

        Identical to get_system_metrics() but omits the temperature block
        from the GraphQL query. The Unraid GraphQL temperature resolver
        triggers smartctl reads for disk sensors which wakes sleeping/standby
        disks. Use this method for frequent polling (e.g. every 30 seconds)
        to avoid disrupting disk power management.

        CPU temperature is still available via info.cpu.packages.temp.
        Temperature will be None in the returned SystemMetrics.

        Returns:
            SystemMetrics model with temperature=None.

        """
        from unraid_api.models import SystemMetrics

        query_str = """
            query {
                metrics {
                    cpu { percentTotal }
                    memory {
                        total used free available active buffcache
                        percentTotal
                        swapTotal swapUsed swapFree percentSwapTotal
                    }
                }
                info {
                    os { uptime }
                    cpu { packages { temp totalPower } }
                }
            }
        """
        result = await self.query(query_str)
        return SystemMetrics.from_response(result)

    async def get_temperature_metrics(self) -> TemperatureMetrics:
        """Get temperature metrics from all sensors.

        Returns temperature data from lm_sensors, smartctl, and IPMI
        providers including per-sensor readings, thresholds, and summary.

        Returns:
            TemperatureMetrics model with summary and sensor data.

        """
        from unraid_api.models import TemperatureMetrics

        query_str = """
            query {
                metrics {
                    temperature {
                        id
                        summary {
                            average
                            hottest { name current { value unit } }
                            coolest { name current { value unit } }
                            warningCount
                            criticalCount
                        }
                        sensors {
                            id name type location
                            current { value unit status }
                            min { value unit }
                            max { value unit }
                            warning critical
                        }
                    }
                }
            }
        """
        result = await self.query(query_str)
        temp_data = (result.get("metrics") or {}).get("temperature") or {}
        return TemperatureMetrics(**temp_data)

    async def get_network_metrics(self) -> list[NetworkMetrics]:
        """Get per-interface network metrics (API 4.35.0+).

        Returns read-only throughput, packet, error, and dropped counters
        for every network interface on the server (bridges, NICs, veth
        pairs, loopback).

        Returns:
            List of NetworkMetrics models, one per interface.

        Raises:
            UnraidAPIError: If the server does not expose metrics.network
                (Unraid API older than 4.35.0).

        """
        from unraid_api.models import NetworkMetrics

        await self.get_capabilities()
        self._require_capability("Network metrics query", "Metrics.network")

        query_str = """
            query {
                metrics {
                    network {
                        id
                        name
                        rxSec
                        txSec
                        operstate
                        bytesReceived
                        bytesSent
                        packetsReceived
                        packetsSent
                        receiveErrors
                        transmitErrors
                        receiveDropped
                        transmitDropped
                    }
                }
            }
        """
        result = await self.query(query_str)
        interfaces = (result.get("metrics") or {}).get("network") or []
        return [NetworkMetrics(**i) for i in interfaces]

    async def typed_get_containers(self) -> list[DockerContainer]:
        """Get all Docker containers as Pydantic models.

        Composes the GraphQL query from server capabilities so older Unraid
        API versions (without fields like `labels`, `isUpdateAvailable`, or
        the full Tailscale subselection) still work.

        Returns:
            List of DockerContainer models.

        """
        from unraid_api.models import DockerContainer

        caps = await self.get_capabilities()
        query_str = self._build_containers_query(caps)
        result = await self.query(query_str)
        containers = result.get("docker", {}).get("containers", []) or []
        return [DockerContainer.from_api_response(c) for c in containers]

    def _build_containers_query(self, caps: ServerCapabilities) -> str:
        """Compose a docker.containers GraphQL query from capabilities.

        Core fields that every Unraid API version has exposed are always
        included. Every other field is gated on introspection so an old
        server never sees a field it cannot resolve. In permissive mode
        (introspection unavailable) every optional field is requested.
        """

        def has(field: str) -> bool:
            return caps.has(f"DockerContainer.{field}")

        def ts_has(field: str) -> bool:
            return caps.has(f"TailscaleStatus.{field}")

        core = [
            "id",
            "names",
            "image",
            "imageId",
            "state",
            "status",
            "autoStart",
        ]
        extended_scalar = [
            f
            for f in (
                "isUpdateAvailable",
                "isOrphaned",
                "webUiUrl",
                "iconUrl",
                "command",
                "created",
                "sizeRootFs",
                "sizeRw",
                "sizeLog",
                "autoStartOrder",
                "autoStartWait",
                "shell",
                "templatePath",
                "projectUrl",
                "registryUrl",
                "supportUrl",
                "tailscaleEnabled",
                "isRebuildReady",
                "lanIpPorts",
                "labels",
                "networkSettings",
                "mounts",
            )
            if has(f)
        ]

        fragments: list[str] = list(core) + extended_scalar

        if has("ports"):
            fragments.append("ports { ip privatePort publicPort type }")
        if has("templatePorts"):
            fragments.append("templatePorts { ip privatePort publicPort type }")
        if has("hostConfig"):
            fragments.append("hostConfig { networkMode }")

        if has("tailscaleStatus"):
            ts_fields = [
                f
                for f in (
                    "hostname",
                    "dnsName",
                    "online",
                    "version",
                    "latestVersion",
                    "updateAvailable",
                    "relay",
                    "relayName",
                    "tailscaleIps",
                    "primaryRoutes",
                    "isExitNode",
                    "webUiUrl",
                    "keyExpiry",
                    "keyExpiryDays",
                    "keyExpired",
                    "backendState",
                    "authUrl",
                )
                if ts_has(f)
            ]
            if ts_has("exitNodeStatus"):
                ts_fields.append("exitNodeStatus { online tailscaleIps }")
            # Always include `online` as a baseline if nothing else matched
            # (old servers exposed at minimum a boolean-shaped status).
            if not ts_fields:
                ts_fields = ["online"]
            fragments.append("tailscaleStatus { " + " ".join(ts_fields) + " }")

        indent = "                        "
        body = ("\n" + indent).join(fragments)
        return (
            "query {\n"
            "            docker {\n"
            "                containers {\n"
            f"                    {body}\n"
            "                }\n"
            "            }\n"
            "        }"
        )

    async def typed_get_containers_safe(self) -> list[DockerContainer]:
        """Get Docker containers WITHOUT expensive fields (safe for polling).

        Identical to typed_get_containers() but omits fields that are
        expensive for the server to resolve: sizeRootFs/sizeRw/sizeLog make
        the Docker daemon compute writable-layer sizes (equivalent to
        ``docker ps --size``), which causes multi-second CPU spikes on every
        poll. Heavy payload fields (mounts, networkSettings, labels) and
        nested selections (ports, templatePorts, hostConfig,
        tailscaleStatus) are omitted as well. Use this method for frequent
        polling (e.g. every 60 seconds).

        Omitted fields are None in the returned models.

        Returns:
            List of DockerContainer models with only cheap scalar fields.

        """
        from unraid_api.models import DockerContainer

        caps = await self.get_capabilities()
        query_str = self._build_containers_query_safe(caps)
        result = await self.query(query_str)
        containers = result.get("docker", {}).get("containers", []) or []
        return [DockerContainer.from_api_response(c) for c in containers]

    def _build_containers_query_safe(self, caps: ServerCapabilities) -> str:
        """Compose a lightweight docker.containers query from capabilities.

        Requests only cheap scalar fields. Expensive fields (sizeRootFs,
        sizeRw, sizeLog), heavy payloads (mounts, networkSettings, labels)
        and nested selections (ports, templatePorts, hostConfig,
        tailscaleStatus) are never included, regardless of capabilities.
        """

        def has(field: str) -> bool:
            return caps.has(f"DockerContainer.{field}")

        core = [
            "id",
            "names",
            "image",
            "imageId",
            "state",
            "status",
            "autoStart",
        ]
        extended_scalar = [
            f
            for f in (
                "autoStartOrder",
                "isUpdateAvailable",
                "iconUrl",
                "webUiUrl",
                "projectUrl",
                "registryUrl",
                "supportUrl",
                "tailscaleEnabled",
            )
            if has(f)
        ]

        fragments = core + extended_scalar
        indent = "                        "
        body = ("\n" + indent).join(fragments)
        return (
            "query {\n"
            "            docker {\n"
            "                containers {\n"
            f"                    {body}\n"
            "                }\n"
            "            }\n"
            "        }"
        )

    async def typed_get_vms(self) -> list[VmDomain]:
        """Get all virtual machines as Pydantic models.

        Returns:
            List of VmDomain models.

        """
        from unraid_api.models import VmDomain

        query_str = """
            query {
                vms {
                    domains {
                        id
                        name
                        state
                    }
                }
            }
        """
        result = await self.query(query_str)
        domains = result.get("vms", {}).get("domains", []) or []
        return [VmDomain(**vm) for vm in domains]

    async def typed_get_ups_devices(self) -> list[UPSDevice]:
        """Get UPS devices as Pydantic models.

        Returns:
            List of UPSDevice models.

        """
        from unraid_api.models import UPSDevice

        query_str = """
            query {
                upsDevices {
                    id
                    name
                    model
                    status
                    battery { chargeLevel estimatedRuntime health }
                    power {
                        inputVoltage outputVoltage loadPercentage
                        nominalPower currentPower
                    }
                }
            }
        """
        result = await self.query(query_str)
        devices = result.get("upsDevices", []) or []
        return [UPSDevice(**d) for d in devices]

    async def typed_get_array(self) -> UnraidArray:
        """Get array status as Pydantic model.

        This is a high-priority method for Home Assistant integration,
        called every 30 seconds. Does NOT wake sleeping disks.

        Returns:
            UnraidArray model with array state, capacity, and disk info.

        """
        from unraid_api.models import ArrayDisk, UnraidArray

        query_str = """
            query {
                array {
                    state
                    capacity {
                        kilobytes { free used total }
                    }
                    parityCheckStatus {
                        status
                        progress
                        running
                        paused
                        errors
                        speed
                    }
                    boot {
                        id name device size temp type
                        fsSize fsUsed fsFree fsType
                    }
                    bootDevices {
                        id name device size status type temp
                        fsSize fsUsed fsFree fsType
                    }
                    parities {
                        id idx name device size status type temp
                        isSpinning rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                    disks {
                        id idx name device size status type temp
                        fsSize fsFree fsUsed fsType
                        isSpinning rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                    caches {
                        id idx name device size status type temp
                        fsSize fsFree fsUsed fsType
                        isSpinning rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                }
            }
        """
        result = await self.query(query_str)
        array_data = result.get("array", {}) or {}

        # Parse nested models
        boot_data = array_data.get("boot")
        boot = ArrayDisk(**boot_data) if boot_data else None

        return UnraidArray(
            state=array_data.get("state"),
            capacity=array_data.get("capacity", {}),
            parityCheckStatus=array_data.get("parityCheckStatus", {}),
            boot=boot,
            bootDevices=[ArrayDisk(**d) for d in (array_data.get("bootDevices") or [])],
            parities=[ArrayDisk(**d) for d in (array_data.get("parities") or [])],
            disks=[ArrayDisk(**d) for d in (array_data.get("disks") or [])],
            caches=[ArrayDisk(**d) for d in (array_data.get("caches") or [])],
        )

    async def typed_get_shares(self) -> list[Share]:
        """Get all shares as Pydantic models.

        Returns:
            List of Share models.

        """
        from unraid_api.models import Share

        query_str = """
            query {
                shares {
                    id
                    name
                    free
                    used
                    size
                    cache
                    include
                    exclude
                    nameOrig
                    allocator
                    splitLevel
                    floor
                    cow
                    color
                    luksStatus
                    comment
                }
            }
        """
        result = await self.query(query_str)
        shares = result.get("shares", []) or []
        return [Share(**s) for s in shares]

    async def get_container_update_statuses(self) -> list[ContainerUpdateStatus]:
        """Get update statuses for all Docker containers.

        Returns:
            List of ContainerUpdateStatus models with name and update status.

        """
        from unraid_api.models import ContainerUpdateStatus

        query_str = """
            query {
                docker {
                    containerUpdateStatuses {
                        name
                        updateStatus
                    }
                }
            }
        """
        result = await self.query(query_str)
        statuses = result.get("docker", {}).get("containerUpdateStatuses", []) or []
        return [ContainerUpdateStatus(**s) for s in statuses]

    async def get_ups_configuration(self) -> UPSConfiguration:
        """Get UPS configuration settings.

        Returns:
            UPSConfiguration model with UPS settings.

        """
        from unraid_api.models import UPSConfiguration

        query_str = """
            query {
                upsConfiguration {
                    service
                    upsCable
                    customUpsCable
                    upsType
                    device
                    overrideUpsCapacity
                    batteryLevel
                    minutes
                    timeout
                    killUps
                    nisIp
                    netServer
                    upsName
                    modelName
                }
            }
        """
        result = await self.query(query_str)
        config_data = result.get("upsConfiguration", {}) or {}
        return UPSConfiguration(**config_data)

    async def get_display_settings(self) -> DisplaySettings:
        """Get display and temperature settings.

        Returns:
            DisplaySettings model with theme, temperature units, and thresholds.

        """
        from unraid_api.models import DisplaySettings

        query_str = """
            query {
                info {
                    display {
                        theme
                        unit
                        scale
                        tabs
                        resize
                        wwn
                        total
                        usage
                        text
                        warning
                        critical
                        hot
                        max
                        locale
                    }
                }
            }
        """
        result = await self.query(query_str)
        display_data = result.get("info", {}).get("display", {}) or {}
        return DisplaySettings(**display_data)

    async def get_docker_port_conflicts(self) -> DockerPortConflicts:
        """Get Docker port conflict information.

        Returns:
            DockerPortConflicts model with LAN port conflicts.

        """
        from unraid_api.models import DockerPortConflicts

        query_str = """
            query {
                docker {
                    portConflicts {
                        lanPorts {
                            containers { name }
                        }
                    }
                }
            }
        """
        result = await self.query(query_str)
        conflicts_data = result.get("docker", {}).get("portConflicts", {}) or {}
        return DockerPortConflicts(**conflicts_data)

    async def get_notification_overview(self) -> NotificationOverview:
        """Get notification overview as Pydantic model.

        Returns notification counts by type (info, warning, alert)
        for both unread and archived notifications.

        Returns:
            NotificationOverview model with notification counts.

        """
        from unraid_api.models import NotificationOverview

        query_str = """
            query {
                notifications {
                    overview {
                        unread { info warning alert total }
                        archive { info warning alert total }
                    }
                }
            }
        """
        result = await self.query(query_str)
        overview_data = result.get("notifications", {}).get("overview", {}) or {}
        return NotificationOverview(**overview_data)

    # =========================================================================
    # Docker Container Methods
    # =========================================================================

    async def start_container(self, container_id: str) -> dict[str, Any]:
        """Start a Docker container.

        Args:
            container_id: Container ID to start.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation StartContainer($id: PrefixedID!) {
                docker {
                    start(id: $id) {
                        id
                        state
                        status
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": container_id})

    async def stop_container(self, container_id: str) -> dict[str, Any]:
        """Stop a Docker container.

        Args:
            container_id: Container ID to stop.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation StopContainer($id: PrefixedID!) {
                docker {
                    stop(id: $id) {
                        id
                        state
                        status
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": container_id})

    # =========================================================================
    # Virtual Machine Methods
    # =========================================================================

    async def start_vm(self, vm_id: str) -> dict[str, Any]:
        """Start a virtual machine.

        Args:
            vm_id: VM ID to start.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation StartVM($id: PrefixedID!) {
                vm {
                    start(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    async def stop_vm(self, vm_id: str) -> dict[str, Any]:
        """Stop a virtual machine.

        Args:
            vm_id: VM ID to stop.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation StopVM($id: PrefixedID!) {
                vm {
                    stop(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    # =========================================================================
    # Array Control Methods
    # =========================================================================

    async def start_array(self) -> dict[str, Any]:
        """Start the Unraid array.

        WARNING: This is a potentially destructive operation.

        Returns:
            Mutation response data with array state.

        """
        mutation = """
            mutation StartArray {
                array {
                    setState(input: { desiredState: START }) {
                        id
                        state
                    }
                }
            }
        """
        return await self.mutate(mutation)

    async def stop_array(self) -> dict[str, Any]:
        """Stop the Unraid array.

        WARNING: This is a destructive operation. All containers and VMs
        using array storage will be affected.

        Returns:
            Mutation response data with array state.

        """
        mutation = """
            mutation StopArray {
                array {
                    setState(input: { desiredState: STOP }) {
                        id
                        state
                    }
                }
            }
        """
        return await self.mutate(mutation)

    # =========================================================================
    # Parity Check Control Methods
    # =========================================================================

    async def start_parity_check(self, *, correct: bool = False) -> dict[str, Any]:
        """Start a parity check.

        Args:
            correct: If True, write corrections to parity. If False, read-only.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation StartParityCheck($correct: Boolean!) {
                parityCheck {
                    start(correct: $correct)
                }
            }
        """
        return await self.mutate(mutation, {"correct": correct})

    async def pause_parity_check(self) -> dict[str, Any]:
        """Pause a running parity check.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation PauseParityCheck {
                parityCheck {
                    pause
                }
            }
        """
        return await self.mutate(mutation)

    async def resume_parity_check(self) -> dict[str, Any]:
        """Resume a paused parity check.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation ResumeParityCheck {
                parityCheck {
                    resume
                }
            }
        """
        return await self.mutate(mutation)

    async def cancel_parity_check(self) -> dict[str, Any]:
        """Cancel a running parity check.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation CancelParityCheck {
                parityCheck {
                    cancel
                }
            }
        """
        return await self.mutate(mutation)

    # =========================================================================
    # Disk Spin Control Methods
    # =========================================================================

    async def spin_up_disk(self, disk_id: str) -> dict[str, Any]:
        """Spin up (mount) a disk in the array.

        Args:
            disk_id: Disk ID to spin up (e.g., "disk:1").

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation SpinUpDisk($id: PrefixedID!) {
                array {
                    mountArrayDisk(id: $id) {
                        id
                        isSpinning
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": disk_id})

    async def spin_down_disk(self, disk_id: str) -> dict[str, Any]:
        """Spin down (unmount) a disk in the array.

        Args:
            disk_id: Disk ID to spin down (e.g., "disk:1").

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation SpinDownDisk($id: PrefixedID!) {
                array {
                    unmountArrayDisk(id: $id) {
                        id
                        isSpinning
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": disk_id})

    # =========================================================================
    # Additional Docker Container Methods
    # =========================================================================

    async def pause_container(self, container_id: str) -> dict[str, Any]:
        """Pause (suspend) a Docker container.

        Args:
            container_id: Container ID to pause.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation PauseContainer($id: PrefixedID!) {
                docker {
                    pause(id: $id) {
                        id
                        state
                        status
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": container_id})

    async def unpause_container(self, container_id: str) -> dict[str, Any]:
        """Unpause (resume) a Docker container.

        Args:
            container_id: Container ID to unpause.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation UnpauseContainer($id: PrefixedID!) {
                docker {
                    unpause(id: $id) {
                        id
                        state
                        status
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": container_id})

    async def update_container(self, container_id: str) -> dict[str, Any]:
        """Update a container to the latest image.

        Args:
            container_id: Container ID to update.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation UpdateContainer($id: PrefixedID!) {
                docker {
                    updateContainer(id: $id) {
                        id
                        names
                        image
                        state
                    }
                }
            }
        """
        return await self.mutate(mutation, {"id": container_id})

    async def update_all_containers(self) -> dict[str, Any]:
        """Update every container that has a pending image update.

        Returns:
            Mutation response data with the list of updated containers.

        Raises:
            UnraidAPIError: If the server does not expose
                docker.updateAllContainers.

        """
        await self.get_capabilities()
        self._require_capability(
            "updateAllContainers mutation", "DockerMutations.updateAllContainers"
        )

        mutation = """
            mutation UpdateAllContainers {
                docker {
                    updateAllContainers {
                        id
                        names
                        image
                        state
                    }
                }
            }
        """
        return await self.mutate(mutation)

    async def update_containers(self, container_ids: list[str]) -> dict[str, Any]:
        """Update the given containers to their latest images.

        Args:
            container_ids: Container IDs to update.

        Returns:
            Mutation response data with the list of updated containers.

        Raises:
            ValueError: If container_ids is empty or contains blank IDs.
            UnraidAPIError: If the server does not expose
                docker.updateContainers.

        """
        cleaned = [i.strip() for i in container_ids]
        if not cleaned or any(not i for i in cleaned):
            raise ValueError("container_ids must be non-empty container IDs")
        # Updating the same container twice in one call is meaningless.
        deduped = list(dict.fromkeys(cleaned))

        await self.get_capabilities()
        self._require_capability(
            "updateContainers mutation", "DockerMutations.updateContainers"
        )

        mutation = """
            mutation UpdateContainers($ids: [PrefixedID!]!) {
                docker {
                    updateContainers(ids: $ids) {
                        id
                        names
                        image
                        state
                    }
                }
            }
        """
        return await self.mutate(mutation, {"ids": deduped})

    async def refresh_docker_digests(self) -> bool:
        """Force a re-check of remote image digests for update detection.

        Refreshes the update-available state of all containers (the
        "check for updates" action in the WebGUI).

        Returns:
            True if the refresh was triggered successfully.

        Raises:
            UnraidAPIError: If the server does not expose
                refreshDockerDigests.

        """
        await self.get_capabilities()
        self._require_capability(
            "refreshDockerDigests mutation", "Mutation.refreshDockerDigests"
        )

        mutation = """
            mutation RefreshDockerDigests {
                refreshDockerDigests
            }
        """
        result = await self.mutate(mutation)
        return bool(result.get("refreshDockerDigests"))

    async def get_containers(self) -> list[dict[str, Any]]:
        """Get all Docker containers.

        Returns:
            List of container data dictionaries.

        """
        # Using core fields guaranteed across API versions
        query_str = """
            query {
                docker {
                    containers {
                        id
                        names
                        image
                        imageId
                        state
                        status
                        autoStart
                        command
                        created
                        isUpdateAvailable
                        isOrphaned
                        webUiUrl
                        iconUrl
                        sizeRootFs
                        sizeRw
                        sizeLog
                        autoStartOrder
                        autoStartWait
                        shell
                        templatePath
                        projectUrl
                        registryUrl
                        supportUrl
                        tailscaleEnabled
                        tailscaleStatus {
                            hostname
                            dnsName
                            online
                            version
                            latestVersion
                            updateAvailable
                            relay
                            relayName
                            tailscaleIps
                            primaryRoutes
                            isExitNode
                            exitNodeStatus { online tailscaleIps }
                            webUiUrl
                            keyExpiry
                            keyExpiryDays
                            keyExpired
                            backendState
                            authUrl
                        }
                        isRebuildReady
                        templatePorts { ip privatePort publicPort type }
                        lanIpPorts
                        hostConfig { networkMode }
                        ports { ip privatePort publicPort type }
                        labels
                        networkSettings
                        mounts
                    }
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("docker", {}).get("containers", []))

    # =========================================================================
    # Additional VM Methods
    # =========================================================================

    async def pause_vm(self, vm_id: str) -> dict[str, Any]:
        """Pause a virtual machine.

        Args:
            vm_id: VM ID to pause.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation PauseVM($id: PrefixedID!) {
                vm {
                    pause(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    async def resume_vm(self, vm_id: str) -> dict[str, Any]:
        """Resume a paused virtual machine.

        Args:
            vm_id: VM ID to resume.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation ResumeVM($id: PrefixedID!) {
                vm {
                    resume(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    async def force_stop_vm(self, vm_id: str) -> dict[str, Any]:
        """Force stop a virtual machine.

        Args:
            vm_id: VM ID to force stop.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation ForceStopVM($id: PrefixedID!) {
                vm {
                    forceStop(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    async def reboot_vm(self, vm_id: str) -> dict[str, Any]:
        """Reboot a virtual machine.

        Args:
            vm_id: VM ID to reboot.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation RebootVM($id: PrefixedID!) {
                vm {
                    reboot(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    async def get_vms(self) -> list[dict[str, Any]]:
        """Get all virtual machines.

        Returns:
            List of VM data dictionaries.

        """
        query_str = """
            query {
                vms {
                    domains {
                        id
                        name
                        state
                    }
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("vms", {}).get("domains", []) or [])

    # =========================================================================
    # System Metrics Methods
    # =========================================================================

    async def get_metrics(self) -> dict[str, Any]:
        """Get system CPU and memory metrics.

        Returns:
            Metrics data with cpu and memory utilization.

        """
        query_str = """
            query {
                metrics {
                    cpu {
                        percentTotal
                        cpus {
                            percentTotal
                            percentUser
                            percentSystem
                            percentIdle
                            percentNice
                            percentIrq
                            percentGuest
                            percentSteal
                        }
                    }
                    memory {
                        total
                        used
                        free
                        available
                        active
                        buffcache
                        percentTotal
                        swapTotal
                        swapUsed
                        swapFree
                        percentSwapTotal
                    }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("metrics", {}))

    async def get_system_info(self) -> dict[str, Any]:
        """Get comprehensive system information.

        Returns:
            System info including OS, CPU, memory, versions.

        """
        query_str = """
            query {
                info {
                    time
                    os {
                        hostname
                        uptime
                        kernel
                        platform
                        distro
                        arch
                    }
                    cpu {
                        manufacturer
                        brand
                        cores
                        threads
                        speed
                    }
                    memory {
                        layout {
                            size
                            bank
                            type
                            clockSpeed
                            manufacturer
                        }
                    }
                    versions {
                        core { unraid api kernel }
                        packages { docker openssl node }
                    }
                    baseboard {
                        manufacturer
                        model
                        memMax
                        memSlots
                    }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("info", {}))

    # =========================================================================
    # Array Information Methods
    # =========================================================================

    async def get_array_status(self) -> dict[str, Any]:
        """Get comprehensive array status.

        This method does NOT wake sleeping disks - it's safe for periodic polling.
        Temperature will be null/0 for disks in standby mode.
        Use the isSpinning field to check if a disk is active.

        Returns:
            Array data including state, capacity, disks, and parity status.

        """
        query_str = """
            query {
                array {
                    state
                    capacity {
                        kilobytes { free used total }
                        disks { free used total }
                    }
                    parityCheckStatus {
                        status
                        progress
                        running
                        paused
                        errors
                        speed
                    }
                    boot {
                        id name device size temp type
                        fsSize fsUsed fsFree fsType
                    }
                    bootDevices {
                        id name device size status type temp
                        fsSize fsUsed fsFree fsType
                    }
                    parities {
                        id idx name device size status type temp
                        isSpinning rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                    disks {
                        id idx name device size status type temp
                        fsSize fsFree fsUsed fsType
                        isSpinning rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                    caches {
                        id idx name device size status type temp
                        fsSize fsFree fsUsed fsType
                        isSpinning rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("array", {}))

    # =========================================================================
    # Share Methods
    # =========================================================================

    async def get_shares(self) -> list[dict[str, Any]]:
        """Get all user shares.

        Returns:
            List of share data dictionaries.

        """
        query_str = """
            query {
                shares {
                    id
                    name
                    free
                    used
                    size
                    cache
                    comment
                    include
                    exclude
                    nameOrig
                    allocator
                    splitLevel
                    floor
                    cow
                    color
                    luksStatus
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("shares", []))

    # =========================================================================
    # UPS Methods
    # =========================================================================

    async def get_ups_status(self) -> list[dict[str, Any]]:
        """Get UPS device status.

        Returns:
            List of UPS device data.

        """
        query_str = """
            query {
                upsDevices {
                    id
                    name
                    model
                    status
                    battery {
                        chargeLevel
                        estimatedRuntime
                        health
                    }
                    power {
                        inputVoltage
                        outputVoltage
                        loadPercentage
                        nominalPower
                        currentPower
                    }
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("upsDevices", []))

    # =========================================================================
    # Notification Methods
    # =========================================================================

    async def get_notifications(
        self,
        notification_type: str = "UNREAD",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get notifications.

        Args:
            notification_type: Type of notifications ("UNREAD" or "ARCHIVE").
            limit: Maximum number of notifications to return.
            offset: Offset for pagination.

        Returns:
            Notifications data including overview and list.

        """
        query_str = """
            query GetNotifications(
                $type: NotificationType!
                $limit: Int!
                $offset: Int!
            ) {
                notifications {
                    overview {
                        unread { info warning alert total }
                        archive { info warning alert total }
                    }
                    list(filter: { type: $type, limit: $limit, offset: $offset }) {
                        id
                        title
                        subject
                        description
                        importance
                        link
                        type
                        timestamp
                        formattedTimestamp
                    }
                }
            }
        """
        result = await self.query(
            query_str,
            {"type": notification_type, "limit": limit, "offset": offset},
        )
        return dict(result.get("notifications", {}))

    # =========================================================================
    # Additional Docker Methods
    # =========================================================================

    async def remove_container(
        self, container_id: str, *, with_image: bool = False
    ) -> dict[str, Any]:
        """Remove a Docker container.

        Args:
            container_id: Container ID to remove.
            with_image: Also remove the container's image.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation RemoveContainer($id: PrefixedID!, $withImage: Boolean!) {
                docker {
                    removeContainer(id: $id, withImage: $withImage)
                }
            }
        """
        return await self.mutate(
            mutation, {"id": container_id, "withImage": with_image}
        )

    # =========================================================================
    # Physical Disk Methods
    # =========================================================================

    async def get_physical_disks(
        self, include_smart: bool = False
    ) -> list[dict[str, Any]]:
        """Get all physical disks.

        WARNING: This query WILL WAKE UP sleeping/standby disks!
        For disk information without waking disks, use get_array_disks() instead.

        Args:
            include_smart: If True, include SMART status (may cause disk wake).

        Returns:
            List of physical disk data dictionaries.

        Note:
            The Unraid API's physical disks endpoint requires disk access which
            spins up any sleeping disks. If you need disk status without waking
            disks, use get_array_disks() which uses the array endpoint that
            provides disk info (including temperature for spinning disks and
            isSpinning status) without forcing disks to wake up.

        """
        if include_smart:
            query_str = """
                query {
                    disks {
                        id
                        device
                        name
                        vendor
                        size
                        type
                        interfaceType
                        temperature
                        isSpinning
                        serialNum
                        firmwareRevision
                        partitions { name fsType size }
                        smartStatus
                    }
                }
            """
        else:
            query_str = """
                query {
                    disks {
                        id
                        device
                        name
                        vendor
                        size
                        type
                        interfaceType
                        temperature
                        isSpinning
                        serialNum
                        firmwareRevision
                        partitions { name fsType size }
                    }
                }
            """
        result = await self.query(query_str)
        return list(result.get("disks", []))

    # Alias for backwards compatibility - deprecated
    async def get_disks(self) -> list[dict[str, Any]]:
        """Get all physical disks.

        DEPRECATED: Use get_physical_disks() or get_array_disks() instead.

        WARNING: This query WILL WAKE UP sleeping/standby disks!
        Use get_array_disks() for disk info without waking disks.

        Returns:
            List of physical disk data dictionaries.

        """
        return await self.get_physical_disks(include_smart=False)

    async def get_array_disks(self) -> dict[str, Any]:
        """Get array disk information WITHOUT waking sleeping disks.

        This is the recommended method for getting disk status in automations
        or periodic polling, as it does NOT wake sleeping/standby disks.

        The array endpoint returns disk information including:
        - Disk state, name, device, size, status, type
        - Temperature (only for spinning disks, null/0 for standby)
        - isSpinning (True if disk is active, False if in standby)
        - Filesystem info (fsSize, fsUsed, fsFree, fsType)

        Returns:
            Dictionary with keys:
            - 'boot': Boot/flash device info (or None)
            - 'disks': List of data disks
            - 'parities': List of parity disks
            - 'caches': List of cache/pool disks

        Note:
            Temperature will be null/0 for disks in standby mode.
            Use the isSpinning field to check if a disk is active.
            This is the same approach used by Home Assistant integrations
            to avoid disrupting disk power management.

        """
        query_str = """
            query {
                array {
                    boot {
                        id name device size status type temp
                        fsSize fsUsed fsFree fsType
                    }
                    bootDevices {
                        id name device size status type temp
                        fsSize fsUsed fsFree fsType
                    }
                    disks {
                        id idx name device size status type temp
                        fsSize fsUsed fsFree fsType isSpinning
                        rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                    parities {
                        id idx name device size status type temp isSpinning
                        rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                    caches {
                        id idx name device size status type temp
                        fsSize fsUsed fsFree fsType isSpinning
                        rotational numReads numWrites numErrors
                        warning critical color format transport comment exportable
                    }
                }
            }
        """
        result = await self.query(query_str)
        array_data = result.get("array", {})
        return {
            "boot": array_data.get("boot"),
            "bootDevices": list(array_data.get("bootDevices", [])),
            "disks": list(array_data.get("disks", [])),
            "parities": list(array_data.get("parities", [])),
            "caches": list(array_data.get("caches", [])),
        }

    # =========================================================================
    # Parity History Methods
    # =========================================================================

    async def get_parity_history(self) -> list[ParityHistoryEntry]:
        """Get parity check history as typed models.

        Returns:
            List of ParityHistoryEntry models.

        """
        from unraid_api.models import ParityHistoryEntry

        query_str = """
            query {
                parityHistory {
                    date
                    duration
                    speed
                    status
                    errors
                }
            }
        """
        result = await self.query(query_str)
        entries = result.get("parityHistory", []) or []
        return [ParityHistoryEntry.model_validate(e) for e in entries]

    # =========================================================================
    # Registration Methods
    # =========================================================================

    async def get_registration(self) -> dict[str, Any]:
        """Get license registration information.

        Returns:
            Registration data including license type and state.

        """

        query_str = """
            query {
                registration {
                    id
                    type
                    state
                    expiration
                    updateExpiration
                    keyFile { location contents }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("registration", {}))

    async def typed_get_registration(self) -> Registration:
        """Get license registration as Pydantic model.

        Returns:
            Registration model with license information.

        """
        from unraid_api.models import Registration

        data = await self.get_registration()
        return Registration(**data)

    # =========================================================================
    # System Variables Methods
    # =========================================================================

    async def get_vars(self) -> dict[str, Any]:
        """Get system variables.

        Returns the unified system configuration from /var/local/emhttp/var.ini.
        Contains hostname, timezone, array state, share counts, and more.

        Returns:
            System vars dictionary with all configuration values.

        """
        query_str = """
            query {
                vars {
                    id
                    version
                    name
                    timeZone
                    comment
                    security
                    workgroup
                    domain
                    domainShort
                    maxArraysz
                    maxCachesz
                    sysModel
                    sysArraySlots
                    sysCacheSlots
                    sysFlashSlots
                    deviceCount
                    useSsl
                    port
                    portssl
                    localTld
                    bindMgt
                    useTelnet
                    porttelnet
                    useSsh
                    portssh
                    useNtp
                    ntpServer1
                    ntpServer2
                    ntpServer3
                    ntpServer4
                    hideDotFiles
                    localMaster
                    enableFruit
                    shareSmbEnabled
                    shareNfsEnabled
                    shareAfpEnabled
                    startArray
                    spindownDelay
                    safeMode
                    startMode
                    configValid
                    configError
                    flashGuid
                    flashProduct
                    flashVendor
                    regCheck
                    regFile
                    regGuid
                    regTy
                    regState
                    regTo
                    mdColor
                    mdNumDisks
                    mdNumDisabled
                    mdNumInvalid
                    mdNumMissing
                    mdResync
                    mdResyncAction
                    mdResyncPos
                    mdState
                    mdVersion
                    sbVersion
                    joinStatus
                    pollAttributesStatus
                    cacheNumDevices
                    fsState
                    fsProgress
                    fsCopyPrcnt
                    fsNumMounted
                    fsNumUnmountable
                    shareCount
                    shareSmbCount
                    shareNfsCount
                    shareAfpCount
                    shareMoverActive
                    csrfToken
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("vars", {}))

    async def typed_get_vars(self) -> Vars:
        """Get system variables as a Pydantic model.

        Returns:
            Vars model with all system configuration.

        """
        from unraid_api.models import Vars

        data = await self.get_vars()
        return Vars(**data)

    # =========================================================================
    # Service Methods
    # =========================================================================

    async def get_services(self) -> list[dict[str, Any]]:
        """Get system services status.

        Returns:
            List of service data dictionaries.

        """
        query_str = """
            query {
                services {
                    id
                    name
                    online
                    uptime { timestamp }
                    version
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("services", []))

    async def typed_get_services(self) -> list[Service]:
        """Get system services as Pydantic models.

        Returns:
            List of Service models.

        """
        from unraid_api.models import Service

        services = await self.get_services()
        return [Service(**s) for s in services]

    # =========================================================================
    # Flash Drive Methods
    # =========================================================================

    async def get_flash(self) -> dict[str, Any]:
        """Get flash drive information.

        Returns:
            Flash drive data dictionary.

        """
        query_str = """
            query {
                flash {
                    id
                    vendor
                    product
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("flash", {}))

    async def typed_get_flash(self) -> Flash:
        """Get flash drive as Pydantic model.

        Returns:
            Flash model with drive information.

        """
        from unraid_api.models import Flash

        data = await self.get_flash()
        return Flash(**data)

    # =========================================================================
    # Owner Methods
    # =========================================================================

    async def get_owner(self) -> dict[str, Any]:
        """Get owner/user information.

        Note: avatar and url fields are only available when signed into Unraid Connect.
        The API may return errors for these non-nullable fields if not signed in.

        Returns:
            Owner data dictionary.

        """
        query_str = """
            query {
                owner {
                    username
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("owner", {}))

    async def typed_get_owner(self) -> Owner:
        """Get owner as Pydantic model.

        Returns:
            Owner model with user information.

        """
        from unraid_api.models import Owner

        data = await self.get_owner()
        return Owner(**data)

    # =========================================================================
    # Plugin Methods
    # =========================================================================

    async def get_plugins(self) -> list[dict[str, Any]]:
        """Get installed plugins.

        Returns:
            List of plugin data dictionaries.

        """
        query_str = """
            query {
                plugins {
                    name
                    version
                    hasApiModule
                    hasCliModule
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("plugins", []))

    async def typed_get_plugins(self) -> list[Plugin]:
        """Get installed plugins as Pydantic models.

        Returns:
            List of Plugin models.

        """
        from unraid_api.models import Plugin

        plugins = await self.get_plugins()
        return [Plugin(**p) for p in plugins]

    # =========================================================================
    # Docker Network Methods
    # =========================================================================

    async def get_docker_networks(self) -> list[dict[str, Any]]:
        """Get Docker networks.

        Returns:
            List of Docker network data dictionaries.

        """
        query_str = """
            query {
                docker {
                    networks {
                        id
                        name
                        created
                        scope
                        driver
                        enableIPv6
                        internal
                        attachable
                        ingress
                        configOnly
                    }
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("docker", {}).get("networks", []))

    async def typed_get_docker_networks(self) -> list[DockerNetwork]:
        """Get Docker networks as Pydantic models.

        Returns:
            List of DockerNetwork models.

        """
        from unraid_api.models import DockerNetwork

        networks = await self.get_docker_networks()
        return [DockerNetwork(**n) for n in networks]

    # =========================================================================
    # Log File Methods
    # =========================================================================

    async def get_log_files(self) -> list[dict[str, Any]]:
        """Get available log files.

        Returns:
            List of log file data dictionaries.

        """
        query_str = """
            query {
                logFiles {
                    name
                    path
                    size
                    modifiedAt
                }
            }
        """
        result = await self.query(query_str)
        return list(result.get("logFiles", []))

    async def typed_get_log_files(self) -> list[LogFile]:
        """Get available log files as Pydantic models.

        Returns:
            List of LogFile models.

        """
        from unraid_api.models import LogFile

        log_files = await self.get_log_files()
        return [LogFile(**lf) for lf in log_files]

    async def get_log_file(self, path: str, lines: int | None = None) -> dict[str, Any]:
        """Get contents of a specific log file.

        Args:
            path: Path to the log file.
            lines: Number of lines to return (optional).

        Returns:
            Log file content data.

        """
        query_str = """
            query GetLogFile($path: String!, $lines: Int) {
                logFile(path: $path, lines: $lines) {
                    path
                    content
                    totalLines
                    startLine
                }
            }
        """
        variables: dict[str, Any] = {"path": path}
        if lines is not None:
            variables["lines"] = lines
        result = await self.query(query_str, variables)
        return dict(result.get("logFile", {}))

    # =========================================================================
    # Cloud/Connect Methods
    # =========================================================================

    async def get_cloud(self) -> dict[str, Any]:
        """Get cloud settings information.

        .. deprecated::
            The ``cloud`` query was removed from the Unraid GraphQL API.
            This method will be removed in a future release.

        Returns:
            Cloud settings data dictionary.

        """
        warnings.warn(
            "get_cloud() is deprecated: the 'cloud' query was removed "
            "from the Unraid GraphQL API and this method will be "
            "removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        query_str = """
            query {
                cloud {
                    error
                    apiKey { valid error }
                    relay { status timeout error }
                    minigraphql { status timeout error }
                    cloud { status ip error }
                    allowedOrigins
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("cloud", {}))

    async def typed_get_cloud(self) -> Cloud:
        """Get cloud settings as Pydantic model.

        .. deprecated::
            The ``cloud`` query was removed from the Unraid GraphQL API.
            This method will be removed in a future release.

        Returns:
            Cloud model with settings information.

        """
        warnings.warn(
            "typed_get_cloud() is deprecated: the 'cloud' query was "
            "removed from the Unraid GraphQL API and this method will "
            "be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        from unraid_api.models import Cloud

        data = await self.get_cloud()
        return Cloud(**data)

    async def get_connect(self) -> dict[str, Any]:
        """Get Unraid Connect information.

        .. deprecated::
            The ``connect`` query was removed from the Unraid GraphQL API.
            This method will be removed in a future release.

        Returns:
            Connect data dictionary.

        """
        warnings.warn(
            "get_connect() is deprecated: the 'connect' query was "
            "removed from the Unraid GraphQL API and this method will "
            "be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        query_str = """
            query {
                connect {
                    id
                    dynamicRemoteAccess {
                        enabledType
                        runningType
                        error
                    }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("connect", {}))

    async def typed_get_connect(self) -> Connect:
        """Get Unraid Connect as Pydantic model.

        .. deprecated::
            The ``connect`` query was removed from the Unraid GraphQL API.
            This method will be removed in a future release.

        Returns:
            Connect model with connection information.

        """
        warnings.warn(
            "typed_get_connect() is deprecated: the 'connect' query "
            "was removed from the Unraid GraphQL API and this method "
            "will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        from unraid_api.models import Connect

        data = await self.get_connect()
        return Connect(**data)

    async def get_remote_access(self) -> dict[str, Any]:
        """Get remote access configuration.

        .. deprecated::
            The ``remoteAccess`` query was removed from the Unraid
            GraphQL API. This method will be removed in a future release.

        Returns:
            Remote access data dictionary.

        """
        warnings.warn(
            "get_remote_access() is deprecated: the 'remoteAccess' "
            "query was removed from the Unraid GraphQL API and this "
            "method will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        query_str = """
            query {
                remoteAccess {
                    accessType
                    forwardType
                    port
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("remoteAccess", {}))

    async def typed_get_remote_access(self) -> RemoteAccess:
        """Get remote access as Pydantic model.

        .. deprecated::
            The ``remoteAccess`` query was removed from the Unraid
            GraphQL API. This method will be removed in a future release.

        Returns:
            RemoteAccess model with configuration.

        """
        warnings.warn(
            "typed_get_remote_access() is deprecated: the "
            "'remoteAccess' query was removed from the Unraid GraphQL "
            "API and this method will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        from unraid_api.models import RemoteAccess

        data = await self.get_remote_access()
        return RemoteAccess(**data)

    # =========================================================================
    # Notification Mutation Methods
    # =========================================================================

    async def archive_notification(self, notification_id: str) -> dict[str, Any]:
        """Archive a notification.

        Args:
            notification_id: ID of the notification to archive.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation ArchiveNotification($id: PrefixedID!) {
                archiveNotification(id: $id) {
                    id
                    title
                }
            }
        """
        return await self.mutate(mutation, {"id": notification_id})

    async def unarchive_notification(self, notification_id: str) -> dict[str, Any]:
        """Mark an archived notification as unread.

        Args:
            notification_id: ID of the notification to unarchive.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation UnarchiveNotification($id: PrefixedID!) {
                unreadNotification(id: $id) {
                    id
                    title
                }
            }
        """
        return await self.mutate(mutation, {"id": notification_id})

    async def delete_notification(
        self,
        notification_id: str,
        notification_type: str = "ARCHIVE",
    ) -> dict[str, Any]:
        """Delete a notification.

        Args:
            notification_id: ID of the notification to delete.
            notification_type: Type of notification ("ARCHIVE" or "UNREAD").
                Defaults to "ARCHIVE".

        Returns:
            Mutation response data with NotificationOverview.

        """
        mutation = """
            mutation DeleteNotification($id: PrefixedID!, $type: NotificationType!) {
                deleteNotification(id: $id, type: $type) {
                    unread { total }
                    archive { total }
                }
            }
        """
        return await self.mutate(
            mutation, {"id": notification_id, "type": notification_type}
        )

    async def archive_all_notifications(self) -> dict[str, Any]:
        """Archive all unread notifications.

        Returns:
            Mutation response data with NotificationOverview.

        """
        mutation = """
            mutation ArchiveAllNotifications {
                archiveAll {
                    unread { total }
                    archive { total }
                }
            }
        """
        return await self.mutate(mutation)

    async def delete_all_notifications(self) -> dict[str, Any]:
        """Delete all archived notifications.

        Returns:
            Mutation response data with NotificationOverview.

        """
        mutation = """
            mutation DeleteArchivedNotifications {
                deleteArchivedNotifications {
                    unread { total }
                    archive { total }
                }
            }
        """
        return await self.mutate(mutation)

    # =========================================================================
    # VM Reset Method
    # =========================================================================

    async def reset_vm(self, vm_id: str) -> dict[str, Any]:
        """Reset a virtual machine (hard reset).

        Args:
            vm_id: VM ID to reset.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation ResetVM($id: PrefixedID!) {
                vm {
                    reset(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": vm_id})

    # =========================================================================
    # Array Disk Management Methods
    # =========================================================================

    async def add_array_disk(
        self, disk_id: str, *, slot: int | None = None
    ) -> dict[str, Any]:
        """Add a disk to the array.

        Args:
            disk_id: Disk ID to add.
            slot: Optional slot number for the disk.

        Returns:
            Mutation response data (UnraidArray).

        """
        mutation = """
            mutation AddArrayDisk($input: ArrayDiskInput!) {
                array {
                    addDiskToArray(input: $input) {
                        state
                        disks { id name status }
                    }
                }
            }
        """
        variables: dict[str, Any] = {"input": {"id": disk_id}}
        if slot is not None:
            variables["input"]["slot"] = slot
        return await self.mutate(mutation, variables)

    async def remove_array_disk(
        self, disk_id: str, *, slot: int | None = None
    ) -> dict[str, Any]:
        """Remove a disk from the array.

        Args:
            disk_id: Disk ID to remove.
            slot: Optional slot number of the disk.

        Returns:
            Mutation response data (UnraidArray).

        """
        mutation = """
            mutation RemoveArrayDisk($input: ArrayDiskInput!) {
                array {
                    removeDiskFromArray(input: $input) {
                        state
                        disks { id name status }
                    }
                }
            }
        """
        variables: dict[str, Any] = {"input": {"id": disk_id}}
        if slot is not None:
            variables["input"]["slot"] = slot
        return await self.mutate(mutation, variables)

    async def clear_disk_stats(self, disk_id: str) -> dict[str, Any]:
        """Clear statistics for an array disk.

        Args:
            disk_id: Disk ID to clear statistics for.

        Returns:
            Mutation response with boolean result.

        """
        mutation = """
            mutation ClearDiskStats($id: PrefixedID!) {
                array {
                    clearArrayDiskStatistics(id: $id)
                }
            }
        """
        return await self.mutate(mutation, {"id": disk_id})

    # =========================================================================
    # Container Convenience Methods
    # =========================================================================

    async def restart_container(
        self, container_id: str, *, delay: float = 1.0
    ) -> dict[str, Any]:
        """Restart a Docker container (stop → wait → start).

        The Unraid GraphQL API does not have a native restart mutation,
        so this convenience method encapsulates the stop/wait/start sequence.

        Args:
            container_id: Container ID to restart.
            delay: Seconds to wait between stop and start (default 1.0).

        Returns:
            Start mutation response data.

        Raises:
            UnraidConnectionError: On network errors.
            UnraidAPIError: On GraphQL errors.

        """
        await self.stop_container(container_id)
        await asyncio.sleep(delay)
        return await self.start_container(container_id)

    # =========================================================================
    # Container Log Methods
    # =========================================================================

    async def get_container_logs(
        self,
        container_id: str,
        *,
        tail: int | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Get logs for a Docker container.

        Args:
            container_id: Container ID to get logs for.
            tail: Number of most recent log lines to return.
            since: DateTime string to get logs since (ISO 8601 format).

        Returns:
            Raw log data with containerId, lines, and cursor.

        """
        query = """
            query GetContainerLogs(
                $id: PrefixedID!,
                $tail: Int,
                $since: DateTime
            ) {
                docker {
                    logs(id: $id, tail: $tail, since: $since) {
                        containerId
                        lines {
                            timestamp
                            message
                        }
                        cursor
                    }
                }
            }
        """
        variables: dict[str, Any] = {"id": container_id}
        if tail is not None:
            variables["tail"] = tail
        if since is not None:
            variables["since"] = since
        result = await self.query(query, variables)
        logs: dict[str, Any] = dict(result.get("docker", {}).get("logs", {}))
        return logs

    async def typed_get_container_logs(
        self,
        container_id: str,
        *,
        tail: int | None = None,
        since: str | None = None,
    ) -> DockerContainerLogs:
        """Get logs for a Docker container as a typed model.

        Args:
            container_id: Container ID to get logs for.
            tail: Number of most recent log lines to return.
            since: DateTime string to get logs since (ISO 8601 format).

        Returns:
            DockerContainerLogs model with log lines.

        """
        from unraid_api.models import DockerContainerLogs

        data = await self.get_container_logs(container_id, tail=tail, since=since)
        return DockerContainerLogs.model_validate(data)

    # =========================================================================
    # User Account Methods
    # =========================================================================

    async def get_me(self) -> dict[str, Any]:
        """Get the current authenticated user's account info.

        Returns:
            Dict with id, name, description, and roles.

        """
        query = """
            query {
                me {
                    id
                    name
                    description
                    roles
                }
            }
        """
        result = await self.query(query)
        me: dict[str, Any] = dict(result.get("me", {}))
        return me

    async def typed_get_me(self) -> UserAccount:
        """Get the current authenticated user as a typed model.

        Returns:
            UserAccount model.

        """
        from unraid_api.models import UserAccount

        data = await self.get_me()
        return UserAccount.model_validate(data)

    # =========================================================================
    # API Key Management Methods
    # =========================================================================

    async def get_api_keys(self) -> list[dict[str, Any]]:
        """Get all API keys.

        Returns:
            List of API key dicts with id, name, description, roles, createdAt.

        """
        query = """
            query {
                apiKeys {
                    id
                    name
                    description
                    roles
                    createdAt
                }
            }
        """
        result = await self.query(query)
        keys: list[dict[str, Any]] = list(result.get("apiKeys", []))
        return keys

    async def typed_get_api_keys(self) -> list[ApiKey]:
        """Get all API keys as typed models.

        Returns:
            List of ApiKey models.

        """
        from unraid_api.models import ApiKey

        data = await self.get_api_keys()
        return [ApiKey.model_validate(item) for item in data]

    async def create_api_key(
        self,
        name: str,
        *,
        description: str | None = None,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new API key.

        Args:
            name: Display name for the key.
            description: Optional description.
            roles: List of roles (e.g., ["ADMIN"], ["VIEWER"]).

        Returns:
            Created API key data including the key value.

        """
        mutation = """
            mutation CreateApiKey($input: ApiKeyCreateInput!) {
                apiKey {
                    create(input: $input) {
                        id
                        key
                        name
                        description
                        roles
                        createdAt
                    }
                }
            }
        """
        input_data: dict[str, Any] = {"name": name}
        if description is not None:
            input_data["description"] = description
        if roles is not None:
            input_data["roles"] = roles
        result = await self.mutate(mutation, {"input": input_data})
        created: dict[str, Any] = dict(result.get("apiKey", {}).get("create", {}))
        return created

    async def update_api_key(
        self,
        key_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing API key.

        Args:
            key_id: API key ID to update.
            name: New display name.
            description: New description.

        Returns:
            Updated API key data.

        """
        mutation = """
            mutation UpdateApiKey($input: ApiKeyUpdateInput!) {
                apiKey {
                    update(input: $input) {
                        id
                        name
                        description
                        roles
                    }
                }
            }
        """
        input_data: dict[str, Any] = {"id": key_id}
        if name is not None:
            input_data["name"] = name
        if description is not None:
            input_data["description"] = description
        result = await self.mutate(mutation, {"input": input_data})
        updated: dict[str, Any] = dict(result.get("apiKey", {}).get("update", {}))
        return updated

    async def delete_api_keys(self, key_ids: list[str]) -> dict[str, Any]:
        """Delete one or more API keys.

        Args:
            key_ids: List of API key IDs to delete.

        Returns:
            Mutation response data.

        """
        mutation = """
            mutation DeleteApiKeys($input: ApiKeyDeleteInput!) {
                apiKey {
                    delete(input: $input)
                }
            }
        """
        return await self.mutate(mutation, {"input": {"ids": key_ids}})

    # =========================================================================
    # Subscription Methods (WebSocket)
    # =========================================================================

    async def subscribe_container_stats(
        self,
    ) -> AsyncGenerator[DockerContainerStats, None]:
        """Subscribe to live Docker container resource statistics.

        Yields DockerContainerStats models with CPU, memory, network,
        and block I/O metrics for all running containers.

        Yields:
            DockerContainerStats for each update event.

        """
        from unraid_api.models import DockerContainerStats

        subscription = """
            subscription {
                dockerContainerStats {
                    id cpuPercent memUsage memPercent netIO blockIO
                }
            }
        """
        async for data in self.subscribe(subscription):
            stats_data = data.get("dockerContainerStats", {})
            yield DockerContainerStats(**stats_data)

    async def subscribe_cpu_metrics(self) -> AsyncGenerator[CpuMetrics, None]:
        """Subscribe to live CPU utilization metrics.

        Yields CpuMetrics models with overall and per-core CPU percentages.

        Yields:
            CpuMetrics for each update event.

        """
        from unraid_api.models import CpuMetrics

        subscription = """
            subscription {
                systemMetricsCpu {
                    percentTotal
                    cpus { percentTotal }
                }
            }
        """
        async for data in self.subscribe(subscription):
            cpu_data = data.get("systemMetricsCpu", {})
            yield CpuMetrics(**cpu_data)

    async def subscribe_cpu_telemetry(
        self,
    ) -> AsyncGenerator[CpuTelemetryMetrics, None]:
        """Subscribe to CPU telemetry (power and temperature).

        Yields CpuTelemetryMetrics models with power consumption
        and temperature readings.

        Yields:
            CpuTelemetryMetrics for each update event.

        """
        from unraid_api.models import CpuTelemetryMetrics

        subscription = """
            subscription {
                systemMetricsCpuTelemetry {
                    totalPower power temp
                }
            }
        """
        async for data in self.subscribe(subscription):
            telemetry_data = data.get("systemMetricsCpuTelemetry", {})
            yield CpuTelemetryMetrics(**telemetry_data)

    async def subscribe_memory_metrics(
        self,
    ) -> AsyncGenerator[MemoryMetrics, None]:
        """Subscribe to live memory utilization metrics.

        Yields MemoryMetrics models with total, used, free memory
        and percentage.

        Yields:
            MemoryMetrics for each update event.

        """
        from unraid_api.models import MemoryMetrics

        subscription = """
            subscription {
                systemMetricsMemory {
                    total used free percentTotal
                }
            }
        """
        async for data in self.subscribe(subscription):
            mem_data = data.get("systemMetricsMemory", {})
            yield MemoryMetrics(**mem_data)

    async def subscribe_network_metrics(
        self,
    ) -> AsyncGenerator[list[NetworkMetrics], None]:
        """Subscribe to live per-interface network metrics (API 4.35.0+).

        Yields a list of NetworkMetrics models (one per interface) for
        each update event.

        Yields:
            List of NetworkMetrics for each update event.

        Raises:
            UnraidAPIError: If the server does not expose the
                systemMetricsNetwork subscription.

        """
        from unraid_api.models import NetworkMetrics

        await self.get_capabilities()
        self._require_capability(
            "systemMetricsNetwork subscription", "Subscription.systemMetricsNetwork"
        )

        subscription = """
            subscription {
                systemMetricsNetwork {
                    id
                    name
                    rxSec
                    txSec
                    operstate
                    bytesReceived
                    bytesSent
                    packetsReceived
                    packetsSent
                    receiveErrors
                    transmitErrors
                    receiveDropped
                    transmitDropped
                }
            }
        """
        async for data in self.subscribe(subscription):
            interfaces = data.get("systemMetricsNetwork") or []
            yield [NetworkMetrics(**i) for i in interfaces]

    async def subscribe_temperature_metrics(
        self,
    ) -> AsyncGenerator[TemperatureMetrics, None]:
        """Subscribe to live temperature metrics.

        Yields TemperatureMetrics models with summary and sensor data
        for all detected temperature sensors.

        Yields:
            TemperatureMetrics for each update event.

        """
        from unraid_api.models import TemperatureMetrics

        subscription = """
            subscription {
                systemMetricsTemperature {
                    id
                    summary {
                        average
                        hottest { name current { value unit } }
                        coolest { name current { value unit } }
                        warningCount
                        criticalCount
                    }
                    sensors {
                        id name type location
                        current { value unit status }
                        min { value unit }
                        max { value unit }
                        warning critical
                    }
                }
            }
        """
        async for data in self.subscribe(subscription):
            temp_data = data.get("systemMetricsTemperature", {})
            yield TemperatureMetrics(**temp_data)

    async def subscribe_ups_updates(
        self,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to UPS status updates.

        Yields raw dictionaries with UPS state changes including
        status and battery charge level.

        Yields:
            Dict with UPS update data for each event.

        """
        subscription = """
            subscription {
                upsUpdates {
                    id status battery { chargeLevel }
                }
            }
        """
        async for data in self.subscribe(subscription):
            yield data.get("upsUpdates", {})

    async def subscribe_array_updates(
        self,
    ) -> AsyncGenerator[ArraySubscriptionUpdate, None]:
        """Subscribe to array state changes.

        Yields ArraySubscriptionUpdate models with array state
        and capacity information.

        Yields:
            ArraySubscriptionUpdate for each state change event.

        """
        from unraid_api.models import ArraySubscriptionUpdate

        subscription = """
            subscription {
                arraySubscription {
                    state
                    capacity { kilobytes { free used total } }
                }
            }
        """
        async for data in self.subscribe(subscription):
            array_data = data.get("arraySubscription", {})
            yield ArraySubscriptionUpdate(**array_data)

    async def subscribe_notification_added(
        self,
    ) -> AsyncGenerator[Notification, None]:
        """Subscribe to new notifications as they are created.

        Yields a ``Notification`` model for each notification raised on
        the Unraid server. Useful for pushing Unraid alerts into Home
        Assistant without polling.

        Yields:
            Notification for each new notification event.

        """
        from unraid_api.models import Notification

        await self.get_capabilities()
        self._require_capability(
            "notificationAdded subscription", "Subscription.notificationAdded"
        )

        subscription = """
            subscription {
                notificationAdded {
                    id
                    title
                    subject
                    description
                    importance
                    link
                    type
                    timestamp
                    formattedTimestamp
                }
            }
        """
        async for data in self.subscribe(subscription):
            payload = data.get("notificationAdded", {})
            yield Notification(**payload)

    async def subscribe_notifications_overview(
        self,
    ) -> AsyncGenerator[NotificationOverview, None]:
        """Subscribe to live notification counts.

        Yields a ``NotificationOverview`` with unread and archive
        counts broken down by importance.

        Yields:
            NotificationOverview for each overview update event.

        """
        from unraid_api.models import NotificationOverview

        await self.get_capabilities()
        self._require_capability(
            "notificationsOverview subscription",
            "Subscription.notificationsOverview",
        )

        subscription = """
            subscription {
                notificationsOverview {
                    unread { info warning alert total }
                    archive { info warning alert total }
                }
            }
        """
        async for data in self.subscribe(subscription):
            payload = data.get("notificationsOverview", {})
            yield NotificationOverview(**payload)

    async def subscribe_notifications_warnings_and_alerts(
        self,
    ) -> AsyncGenerator[list[Notification], None]:
        """Subscribe to the live list of warning/alert notifications.

        Yields a list of ``Notification`` models whenever the server's
        warnings-and-alerts list changes.

        Yields:
            List of Notification models for each update event.

        """
        from unraid_api.models import Notification

        await self.get_capabilities()
        self._require_capability(
            "notificationsWarningsAndAlerts subscription",
            "Subscription.notificationsWarningsAndAlerts",
        )

        subscription = """
            subscription {
                notificationsWarningsAndAlerts {
                    id
                    title
                    subject
                    description
                    importance
                    link
                    type
                    timestamp
                    formattedTimestamp
                }
            }
        """
        async for data in self.subscribe(subscription):
            items = data.get("notificationsWarningsAndAlerts") or []
            yield [Notification(**item) for item in items]

    async def subscribe_parity_history(
        self,
    ) -> AsyncGenerator[ParityCheck, None]:
        """Subscribe to live parity-check progress.

        Yields a ``ParityCheck`` model for each status update emitted
        by the server during a parity check or parity history event.

        Yields:
            ParityCheck for each parity-history update event.

        """
        from unraid_api.models import ParityCheck

        await self.get_capabilities()
        self._require_capability(
            "parityHistorySubscription", "Subscription.parityHistorySubscription"
        )

        subscription = """
            subscription {
                parityHistorySubscription {
                    date
                    duration
                    speed
                    status
                    errors
                    progress
                    correcting
                    paused
                    running
                }
            }
        """
        async for data in self.subscribe(subscription):
            payload = data.get("parityHistorySubscription", {})
            yield ParityCheck(**payload)

    # =========================================================================
    # Network Query
    # =========================================================================

    async def get_network(self) -> dict[str, Any]:
        """Get network configuration and access URLs.

        Returns:
            Dict with ``id`` and ``accessUrls`` entries as returned by
            the server.

        """
        await self.get_capabilities()
        self._require_capability("network query", "Query.network")

        query_str = """
            query {
                network {
                    id
                    accessUrls { type name ipv4 ipv6 }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("network", {}))

    async def typed_get_network(self) -> Network:
        """Get network configuration as a Pydantic model.

        Returns:
            Network model with parsed access URLs.

        """
        from unraid_api.models import Network

        data = await self.get_network()
        return Network(**data)

    # =========================================================================
    # Notification Mutations
    # =========================================================================

    async def create_notification(
        self,
        *,
        title: str,
        subject: str,
        description: str,
        importance: str,
        link: str | None = None,
    ) -> Notification:
        """Create a new notification on the Unraid server.

        Args:
            title: Notification title.
            subject: Short subject line.
            description: Full description body.
            importance: One of "INFO", "WARNING", "ALERT".
            link: Optional URL for click-through.

        Returns:
            Created Notification model.

        """
        from unraid_api.models import Notification

        await self.get_capabilities()
        self._require_capability(
            "createNotification mutation", "Mutation.createNotification"
        )

        mutation = """
            mutation CreateNotification($input: NotificationData!) {
                createNotification(input: $input) {
                    id
                    title
                    subject
                    description
                    importance
                    link
                    type
                    timestamp
                    formattedTimestamp
                }
            }
        """
        input_data: dict[str, Any] = {
            "title": title,
            "subject": subject,
            "description": description,
            "importance": importance,
        }
        if link is not None:
            input_data["link"] = link
        result = await self.mutate(mutation, {"input": input_data})
        created: dict[str, Any] = dict(result.get("createNotification") or {})
        return Notification(**created)

    async def notify_if_unique(
        self,
        *,
        title: str,
        subject: str,
        description: str,
        importance: str,
        link: str | None = None,
    ) -> Notification | None:
        """Create a notification only if no identical one already exists.

        Args:
            title: Notification title.
            subject: Short subject line.
            description: Full description body.
            importance: One of "INFO", "WARNING", "ALERT".
            link: Optional URL for click-through.

        Returns:
            Created Notification model, or None if a duplicate already
            existed and the server suppressed it.

        """
        from unraid_api.models import Notification

        await self.get_capabilities()
        self._require_capability("notifyIfUnique mutation", "Mutation.notifyIfUnique")

        mutation = """
            mutation NotifyIfUnique($input: NotificationData!) {
                notifyIfUnique(input: $input) {
                    id
                    title
                    subject
                    description
                    importance
                    link
                    type
                    timestamp
                    formattedTimestamp
                }
            }
        """
        input_data: dict[str, Any] = {
            "title": title,
            "subject": subject,
            "description": description,
            "importance": importance,
        }
        if link is not None:
            input_data["link"] = link
        result = await self.mutate(mutation, {"input": input_data})
        payload = result.get("notifyIfUnique")
        if payload is None:
            return None
        return Notification(**payload)

    # =========================================================================
    # Temperature Config Mutation
    # =========================================================================

    async def update_temperature_config(
        self,
        *,
        enabled: bool | None = None,
        polling_interval: int | None = None,
        default_unit: str | None = None,
        sensors: dict[str, Any] | None = None,
        thresholds: dict[str, Any] | None = None,
        history: dict[str, Any] | None = None,
    ) -> bool:
        """Update server-side temperature monitoring configuration.

        Args:
            enabled: Enable or disable temperature monitoring.
            polling_interval: Polling interval in seconds.
            default_unit: "CELSIUS" or "FAHRENHEIT".
            sensors: Optional SensorsConfigInput dict.
            thresholds: Optional ThresholdsConfigInput dict with keys
                ``cpu_warning``, ``cpu_critical``, ``disk_warning``,
                ``disk_critical``, ``warning``, ``critical``.
            history: Optional HistoryConfigInput dict with ``max_readings``
                and ``retention_ms``.

        Returns:
            True when the server accepted the new configuration.

        """
        await self.get_capabilities()
        self._require_capability(
            "updateTemperatureConfig mutation",
            "Mutation.updateTemperatureConfig",
        )

        mutation = """
            mutation UpdateTemperatureConfig($input: TemperatureConfigInput!) {
                updateTemperatureConfig(input: $input)
            }
        """
        input_data: dict[str, Any] = {}
        if enabled is not None:
            input_data["enabled"] = enabled
        if polling_interval is not None:
            input_data["polling_interval"] = polling_interval
        if default_unit is not None:
            input_data["default_unit"] = default_unit
        if sensors is not None:
            input_data["sensors"] = sensors
        if thresholds is not None:
            input_data["thresholds"] = thresholds
        if history is not None:
            input_data["history"] = history
        result = await self.mutate(mutation, {"input": input_data})
        return bool(result.get("updateTemperatureConfig", False))

    # =========================================================================
    # System Time Methods (Unraid 7.3 / API 4.3x)
    # =========================================================================

    async def get_system_time(self) -> SystemTime:
        """Get server system-time configuration.

        Returns:
            SystemTime model with current time, NTP servers, time zone, and
            whether NTP synchronization is enabled.

        """
        from unraid_api.models import SystemTime

        await self.get_capabilities()
        self._require_capability("System time query", "Query.systemTime")

        query_str = """
            query {
                systemTime {
                    currentTime
                    ntpServers
                    timeZone
                    useNtp
                }
            }
        """
        result = await self.query(query_str)
        return SystemTime(**(result.get("systemTime") or {}))

    async def get_timezone_options(self) -> list[TimeZoneOption]:
        """Get the list of selectable time-zone options.

        Returns:
            List of TimeZoneOption models (label/value pairs).

        """
        from unraid_api.models import TimeZoneOption

        await self.get_capabilities()
        self._require_capability("Time-zone options query", "Query.timeZoneOptions")

        query_str = """
            query {
                timeZoneOptions {
                    label
                    value
                }
            }
        """
        result = await self.query(query_str)
        options = result.get("timeZoneOptions") or []
        return [TimeZoneOption(**o) for o in options]

    async def update_system_time(
        self,
        *,
        time_zone: str | None = None,
        use_ntp: bool | None = None,
        ntp_servers: list[str] | None = None,
        manual_date_time: str | None = None,
    ) -> SystemTime:
        """Update server system-time configuration.

        Only the provided arguments are sent to the server; omitted arguments
        are left unchanged.

        Args:
            time_zone: IANA time-zone name (e.g., "Australia/Brisbane").
            use_ntp: Enable or disable NTP time synchronization.
            ntp_servers: List of NTP server hostnames.
            manual_date_time: ISO-8601 timestamp to set when NTP is disabled.

        Returns:
            SystemTime model with the updated configuration.

        """
        from unraid_api.models import SystemTime

        await self.get_capabilities()
        self._require_capability(
            "updateSystemTime mutation", "Mutation.updateSystemTime"
        )

        mutation = """
            mutation UpdateSystemTime($input: UpdateSystemTimeInput!) {
                updateSystemTime(input: $input) {
                    currentTime
                    ntpServers
                    timeZone
                    useNtp
                }
            }
        """
        input_data: dict[str, Any] = {}
        if time_zone is not None:
            input_data["timeZone"] = time_zone
        if use_ntp is not None:
            input_data["useNtp"] = use_ntp
        if ntp_servers is not None:
            input_data["ntpServers"] = ntp_servers
        if manual_date_time is not None:
            input_data["manualDateTime"] = manual_date_time
        result = await self.mutate(mutation, {"input": input_data})
        return SystemTime(**(result.get("updateSystemTime") or {}))

    # =========================================================================
    # Disk & UPS Extra Methods (Unraid 7.3 / API 4.3x)
    # =========================================================================

    async def get_assignable_disks(self) -> list[PhysicalDisk]:
        """Get disks that can be assigned to the array.

        WARNING: This queries the physical-disk endpoint and WILL WAKE
        sleeping/standby disks. Use sparingly.

        Returns:
            List of PhysicalDisk models for unassigned/assignable disks.

        """
        from unraid_api.models import PhysicalDisk

        await self.get_capabilities()
        self._require_capability("Assignable disks query", "Query.assignableDisks")

        query_str = """
            query {
                assignableDisks {
                    id
                    device
                    name
                    vendor
                    size
                    type
                    interfaceType
                    temperature
                    isSpinning
                    serialNum
                    firmwareRevision
                    partitions { name fsType size }
                }
            }
        """
        result = await self.query(query_str)
        disks = result.get("assignableDisks") or []
        return [PhysicalDisk(**d) for d in disks]

    async def get_disk(self, disk_id: str) -> PhysicalDisk:
        """Get a single physical disk by ID.

        WARNING: This queries the physical-disk endpoint and WILL WAKE the
        disk if it is sleeping. Use get_array_disks() for standby-safe status.

        Args:
            disk_id: Disk ID (PrefixedID, e.g., "disk:sda").

        Returns:
            PhysicalDisk model.

        """
        from unraid_api.models import PhysicalDisk

        await self.get_capabilities()
        self._require_capability("Disk query", "Query.disk")

        query_str = """
            query GetDisk($id: PrefixedID!) {
                disk(id: $id) {
                    id
                    device
                    name
                    vendor
                    size
                    type
                    interfaceType
                    temperature
                    isSpinning
                    serialNum
                    firmwareRevision
                    smartStatus
                    partitions { name fsType size }
                }
            }
        """
        result = await self.query(query_str, {"id": disk_id})
        return PhysicalDisk(**(result.get("disk") or {}))

    async def typed_get_ups_device(self, device_id: str) -> UPSDevice | None:
        """Get a single UPS device by ID.

        Args:
            device_id: UPS device ID (PrefixedID).

        Returns:
            UPSDevice model, or None if no device with that ID exists.

        """
        from unraid_api.models import UPSDevice

        await self.get_capabilities()
        self._require_capability("UPS device query", "Query.upsDeviceById")

        query_str = """
            query GetUpsDevice($id: String!) {
                upsDeviceById(id: $id) {
                    id
                    name
                    model
                    status
                    battery { chargeLevel estimatedRuntime health }
                    power {
                        inputVoltage outputVoltage loadPercentage
                        nominalPower currentPower
                    }
                }
            }
        """
        result = await self.query(query_str, {"id": device_id})
        device = result.get("upsDeviceById")
        if device is None:
            return None
        return UPSDevice(**device)

    async def subscribe_display(
        self,
    ) -> AsyncGenerator[DisplaySettings, None]:
        """Subscribe to display/theme setting changes.

        Yields a DisplaySettings model whenever the server's display
        configuration (theme, temperature unit, thresholds, etc.) changes.

        Yields:
            DisplaySettings for each change event.

        """
        from unraid_api.models import DisplaySettings

        await self.get_capabilities()
        self._require_capability(
            "displaySubscription subscription", "Subscription.displaySubscription"
        )

        subscription = """
            subscription {
                displaySubscription {
                    theme
                    unit
                    scale
                    tabs
                    resize
                    wwn
                    total
                    usage
                    text
                    warning
                    critical
                    hot
                    max
                    locale
                }
            }
        """
        async for data in self.subscribe(subscription):
            yield DisplaySettings(**(data.get("displaySubscription") or {}))

    # =========================================================================
    # Curated Admin Methods (Unraid 7.3 / API 4.3x)
    # =========================================================================

    async def get_settings(self) -> Settings:
        """Get server settings (read-only diagnostic view).

        Returns the API configuration block and the unified settings form
        payload. Intended for diagnostics; this library does not expose the
        corresponding write mutations.

        Returns:
            Settings model.

        """
        from unraid_api.models import Settings

        await self.get_capabilities()
        self._require_capability("Settings query", "Query.settings")

        query_str = """
            query {
                settings {
                    id
                    api {
                        version
                        sandbox
                        plugins
                        extraOrigins
                        ssoSubIds
                    }
                    unified {
                        values
                        dataSchema
                        uiSchema
                    }
                }
            }
        """
        result = await self.query(query_str)
        return Settings(**(result.get("settings") or {}))

    async def configure_ups(
        self,
        *,
        service: str | None = None,
        ups_cable: str | None = None,
        custom_ups_cable: str | None = None,
        ups_type: str | None = None,
        device: str | None = None,
        override_ups_capacity: int | None = None,
        battery_level: int | None = None,
        minutes: int | None = None,
        timeout: int | None = None,  # noqa: ASYNC109 — UPS config field, not an async timeout
        kill_ups: str | None = None,
    ) -> bool:
        """Configure UPS (apcupsd) settings.

        Pairs with get_ups_configuration(). Only the provided arguments are
        sent to the server; omitted arguments are left unchanged.

        Args:
            service: UPS service state (e.g., "ENABLE"/"DISABLE").
            ups_cable: Cable type enum value.
            custom_ups_cable: Custom cable string when ups_cable is custom.
            ups_type: UPS type enum value (e.g., "USB").
            device: UPS device path.
            override_ups_capacity: Override capacity (VA/W) value.
            battery_level: Battery-level shutdown threshold (percent).
            minutes: Runtime-remaining shutdown threshold (minutes).
            timeout: Shutdown timeout (seconds).
            kill_ups: Kill-power-on-shutdown enum value.

        Returns:
            True when the server accepted the configuration.

        """
        await self.get_capabilities()
        self._require_capability("configureUps mutation", "Mutation.configureUps")

        mutation = """
            mutation ConfigureUps($config: UPSConfigInput!) {
                configureUps(config: $config)
            }
        """
        config: dict[str, Any] = {}
        if service is not None:
            config["service"] = service
        if ups_cable is not None:
            config["upsCable"] = ups_cable
        if custom_ups_cable is not None:
            config["customUpsCable"] = custom_ups_cable
        if ups_type is not None:
            config["upsType"] = ups_type
        if device is not None:
            config["device"] = device
        if override_ups_capacity is not None:
            config["overrideUpsCapacity"] = override_ups_capacity
        if battery_level is not None:
            config["batteryLevel"] = battery_level
        if minutes is not None:
            config["minutes"] = minutes
        if timeout is not None:
            config["timeout"] = timeout
        if kill_ups is not None:
            config["killUps"] = kill_ups
        result = await self.mutate(mutation, {"config": config})
        return bool(result.get("configureUps", False))

    # =========================================================================
    # Network Interfaces (API 4.35.0+)
    # =========================================================================

    async def get_network_interfaces(self) -> list[dict[str, Any]]:
        """Get detailed network interface configuration.

        Returns:
            List of raw interface dicts with address, DHCP, VLAN, and link state data.

        """
        query_str = """
            query {
                networkInterfaces {
                    id
                    name
                    description
                    ipAddress
                    netmask
                    gateway
                    macAddress
                    speed
                    duplex
                    mtu
                    internal
                    virtual
                    useDhcp
                    useDhcp6
                    protocol
                    operstate
                    status
                    type
                    vlanId
                    ipv4Addresses { address netmask }
                    ipv6Address
                    ipv6Gateway
                    ipv6Netmask
                    ipv6Addresses { address prefixLength }
                }
            }
        """
        result = await self.query(query_str)
        return result.get("networkInterfaces") or []

    async def typed_get_network_interfaces(
        self,
    ) -> list[InfoNetworkInterface]:
        """Get detailed network interfaces as typed Pydantic models.

        Returns:
            List of InfoNetworkInterface instances.

        """
        from unraid_api.models import InfoNetworkInterface

        data = await self.get_network_interfaces()
        return [InfoNetworkInterface(**item) for item in data]

    # =========================================================================
    # Docker Organizer & Folder Management
    # =========================================================================

    async def get_docker_organizer(self, skip_cache: bool = False) -> dict[str, Any]:
        """Get Docker container organizer hierarchy and folder views.

        Args:
            skip_cache: Whether to bypass backend caching.

        Returns:
            Raw organizer dictionary.

        """
        query_str = """
            query GetDockerOrganizer($skipCache: Boolean) {
                docker {
                    organizer(skipCache: $skipCache) {
                        version
                        views {
                            id
                            name
                            rootId
                            prefs
                            flatEntries {
                                id
                                name
                                type
                                parentId
                                childrenIds
                                depth
                                hasChildren
                                path
                                position
                            }
                        }
                    }
                }
            }
        """
        result = await self.query(query_str, {"skipCache": skip_cache})
        docker_data = result.get("docker") or {}
        return docker_data.get("organizer") or {}

    async def typed_get_docker_organizer(
        self, skip_cache: bool = False
    ) -> ResolvedOrganizerV1:
        """Get Docker organizer hierarchy as a typed Pydantic model.

        Args:
            skip_cache: Whether to bypass backend caching.

        Returns:
            ResolvedOrganizerV1 model instance.

        """
        from unraid_api.models import ResolvedOrganizerV1

        data = await self.get_docker_organizer(skip_cache=skip_cache)
        return ResolvedOrganizerV1(**data)

    async def create_docker_folder(
        self,
        name: str,
        parent_id: str | None = None,
        children_ids: list[str] | None = None,
    ) -> ResolvedOrganizerV1:
        """Create a new Docker organizer folder.

        Args:
            name: Name of the new folder.
            parent_id: Optional parent folder ID.
            children_ids: Optional list of container IDs to place in folder.

        Returns:
            Updated ResolvedOrganizerV1 model.

        """
        from unraid_api.models import ResolvedOrganizerV1

        mutation = """
            mutation CreateDockerFolder(
                $name: String!, $parentId: String, $childrenIds: [String!]
            ) {
                createDockerFolder(
                    name: $name, parentId: $parentId, childrenIds: $childrenIds
                ) {
                    version
                    views {
                        id
                        name
                        rootId
                        prefs
                        flatEntries {
                            id
                            name
                            type
                            parentId
                            childrenIds
                            depth
                            hasChildren
                            path
                            position
                        }
                    }
                }
            }
        """
        result = await self.mutate(
            mutation,
            {
                "name": name,
                "parentId": parent_id,
                "childrenIds": children_ids or [],
            },
        )
        return ResolvedOrganizerV1(**(result.get("createDockerFolder") or {}))

    async def rename_docker_folder(
        self, folder_id: str, new_name: str
    ) -> ResolvedOrganizerV1:
        """Rename an existing Docker organizer folder.

        Args:
            folder_id: ID of the folder to rename.
            new_name: New name for the folder.

        Returns:
            Updated ResolvedOrganizerV1 model.

        """
        from unraid_api.models import ResolvedOrganizerV1

        mutation = """
            mutation RenameDockerFolder($folderId: String!, $newName: String!) {
                renameDockerFolder(folderId: $folderId, newName: $newName) {
                    version
                    views {
                        id
                        name
                        rootId
                        prefs
                        flatEntries {
                            id
                            name
                            type
                            parentId
                            childrenIds
                            depth
                            hasChildren
                            path
                            position
                        }
                    }
                }
            }
        """
        result = await self.mutate(
            mutation, {"folderId": folder_id, "newName": new_name}
        )
        return ResolvedOrganizerV1(**(result.get("renameDockerFolder") or {}))

    async def delete_docker_entries(self, entry_ids: list[str]) -> ResolvedOrganizerV1:
        """Delete entries (folders) from the Docker organizer.

        Args:
            entry_ids: List of folder/entry IDs to remove.

        Returns:
            Updated ResolvedOrganizerV1 model.

        """
        from unraid_api.models import ResolvedOrganizerV1

        mutation = """
            mutation DeleteDockerEntries($entryIds: [String!]!) {
                deleteDockerEntries(entryIds: $entryIds) {
                    version
                    views {
                        id
                        name
                        rootId
                        prefs
                        flatEntries {
                            id
                            name
                            type
                            parentId
                            childrenIds
                            depth
                            hasChildren
                            path
                            position
                        }
                    }
                }
            }
        """
        result = await self.mutate(mutation, {"entryIds": entry_ids})
        return ResolvedOrganizerV1(**(result.get("deleteDockerEntries") or {}))

    async def move_docker_entries_to_folder(
        self,
        source_entry_ids: list[str],
        destination_folder_id: str | None = None,
    ) -> ResolvedOrganizerV1:
        """Move Docker containers or folders into a target folder.

        Args:
            source_entry_ids: List of container/folder IDs to move.
            destination_folder_id: Target folder ID (or None for root).

        Returns:
            Updated ResolvedOrganizerV1 model.

        """
        from unraid_api.models import ResolvedOrganizerV1

        mutation = """
            mutation MoveDockerEntries(
                $sourceEntryIds: [String!]!, $destinationFolderId: String
            ) {
                moveDockerEntriesToFolder(
                    sourceEntryIds: $sourceEntryIds,
                    destinationFolderId: $destinationFolderId
                ) {
                    version
                    views {
                        id
                        name
                        rootId
                        prefs
                        flatEntries {
                            id
                            name
                            type
                            parentId
                            childrenIds
                            depth
                            hasChildren
                            path
                            position
                        }
                    }
                }
            }
        """
        result = await self.mutate(
            mutation,
            {
                "sourceEntryIds": source_entry_ids,
                "destinationFolderId": destination_folder_id,
            },
        )
        return ResolvedOrganizerV1(**(result.get("moveDockerEntriesToFolder") or {}))

    async def update_container_autostart(
        self,
        entries: list[dict[str, Any]],
        persist_user_preferences: bool = True,
    ) -> bool:
        """Update container autostart configuration.

        Args:
            entries: List of autostart entry dicts with id, autoStart,
                autoStartOrder, and autoStartWait.
            persist_user_preferences: Whether to persist user preferences.

        Returns:
            True if the configuration was saved successfully.

        """
        mutation = """
            mutation UpdateAutostartConfig(
                $entries: [DockerAutostartEntryInput!]!,
                $persist: Boolean
            ) {
                docker {
                    updateAutostartConfiguration(
                        entries: $entries,
                        persistUserPreferences: $persist
                    )
                }
            }
        """
        result = await self.mutate(
            mutation,
            {"entries": entries, "persist": persist_user_preferences},
        )
        docker_data = result.get("docker") or {}
        return bool(docker_data.get("updateAutostartConfiguration", False))

    # =========================================================================
    # Array & Disk Control Mutations
    # =========================================================================

    async def mount_array_disk(self, disk_id: str) -> ArrayDisk | None:
        """Mount an individual array or pool disk.

        Args:
            disk_id: PrefixedID of the disk.

        Returns:
            Updated ArrayDisk model or None.

        """
        from unraid_api.models import ArrayDisk

        mutation = """
            mutation MountDisk($id: PrefixedID!) {
                array {
                    mountArrayDisk(id: $id) {
                        id idx name device status temp isSpinning
                    }
                }
            }
        """
        result = await self.mutate(mutation, {"id": disk_id})
        array_data = result.get("array") or {}
        disk_data = array_data.get("mountArrayDisk")
        return ArrayDisk(**disk_data) if disk_data else None

    async def unmount_array_disk(self, disk_id: str) -> ArrayDisk | None:
        """Unmount an individual array or pool disk.

        Args:
            disk_id: PrefixedID of the disk.

        Returns:
            Updated ArrayDisk model or None.

        """
        from unraid_api.models import ArrayDisk

        mutation = """
            mutation UnmountDisk($id: PrefixedID!) {
                array {
                    unmountArrayDisk(id: $id) {
                        id idx name device status temp isSpinning
                    }
                }
            }
        """
        result = await self.mutate(mutation, {"id": disk_id})
        array_data = result.get("array") or {}
        disk_data = array_data.get("unmountArrayDisk")
        return ArrayDisk(**disk_data) if disk_data else None

    async def clear_array_disk_statistics(self, disk_id: str) -> bool:
        """Clear/reset disk read, write, and error statistics.

        Args:
            disk_id: PrefixedID of the disk.

        Returns:
            True if statistics were cleared successfully.

        """
        mutation = """
            mutation ClearDiskStats($id: PrefixedID!) {
                array {
                    clearArrayDiskStatistics(id: $id)
                }
            }
        """
        result = await self.mutate(mutation, {"id": disk_id})
        array_data = result.get("array") or {}
        return bool(array_data.get("clearArrayDiskStatistics", False))

    # =========================================================================
    # Plugin Management Queries & Operations
    # =========================================================================

    async def get_installed_unraid_plugins(self) -> list[str]:
        """Get list of installed Unraid plugin identifiers/URLs.

        Returns:
            List of plugin file/package names.

        """
        query_str = """
            query {
                installedUnraidPlugins
            }
        """
        result = await self.query(query_str)
        return result.get("installedUnraidPlugins") or []

    async def get_plugin_install_operations(
        self,
    ) -> list[PluginInstallOperation]:
        """Get background plugin install operations.

        Returns:
            List of PluginInstallOperation models.

        """
        from unraid_api.models import PluginInstallOperation

        query_str = """
            query {
                pluginInstallOperations {
                    id name url status output createdAt updatedAt finishedAt
                }
            }
        """
        result = await self.query(query_str)
        items = result.get("pluginInstallOperations") or []
        return [PluginInstallOperation(**op) for op in items]

    async def get_plugin_install_operation(
        self, operation_id: str
    ) -> PluginInstallOperation | None:
        """Get status of a specific plugin install operation.

        Args:
            operation_id: ID of the operation.

        Returns:
            PluginInstallOperation instance or None.

        """
        from unraid_api.models import PluginInstallOperation

        query_str = """
            query GetPluginInstallOp($operationId: ID!) {
                pluginInstallOperation(operationId: $operationId) {
                    id name url status output createdAt updatedAt finishedAt
                }
            }
        """
        result = await self.query(query_str, {"operationId": operation_id})
        op = result.get("pluginInstallOperation")
        return PluginInstallOperation(**op) if op else None

    # =========================================================================
    # Server Queries & Identity Mutations
    # =========================================================================

    async def get_servers(self) -> list[dict[str, Any]]:
        """Get all servers in the Unraid Connect/local network.

        Returns:
            List of raw server dicts.

        """
        query_str = """
            query {
                servers {
                    id name guid lanip wanip localurl remoteurl status comment apikey
                    owner { id username avatar url }
                }
            }
        """
        result = await self.query(query_str)
        return result.get("servers") or []

    async def typed_get_servers(self) -> list[Server]:
        """Get all servers in the network as typed Pydantic models.

        Returns:
            List of Server models.

        """
        from unraid_api.models import Server

        data = await self.get_servers()
        return [Server(**s) for s in data]

    async def get_server(self) -> dict[str, Any]:
        """Get current server identity as a raw dictionary.

        Returns:
            Server data dictionary or empty dictionary.

        """
        query_str = """
            query {
                server {
                    id name guid lanip wanip localurl remoteurl status comment apikey
                    owner { id username avatar url }
                }
            }
        """
        result = await self.query(query_str)
        return dict(result.get("server") or {})

    async def typed_get_server(self) -> Server | None:
        """Get current server identity as a typed Pydantic model.

        Returns:
            Server model instance or None.

        """
        from unraid_api.models import Server

        data = await self.get_server()
        return Server(**data) if data else None

    async def update_server_identity(
        self,
        name: str | None = None,
        comment: str | None = None,
        sys_model: str | None = None,
    ) -> Server:
        """Update server name, comment, or model.

        Args:
            name: New server name.
            comment: New server description.
            sys_model: Custom system model string.

        Returns:
            Updated Server model instance.

        """
        from unraid_api.models import Server

        mutation = """
            mutation UpdateServerIdentity(
                $name: String, $comment: String, $sysModel: String
            ) {
                updateServerIdentity(
                    name: $name, comment: $comment, sysModel: $sysModel
                ) {
                    id
                    name
                    comment
                    guid
                    lanip
                    wanip
                    localurl
                    remoteurl
                    status
                    apikey
                }
            }
        """
        variables: dict[str, Any] = {}
        if name is not None:
            variables["name"] = name
        if comment is not None:
            variables["comment"] = comment
        if sys_model is not None:
            variables["sysModel"] = sys_model
        result = await self.mutate(mutation, variables)
        return Server(**(result.get("updateServerIdentity") or {}))

    # =========================================================================
    # Batch Notification Mutations
    # =========================================================================

    async def archive_notifications(
        self, notification_ids: list[str]
    ) -> NotificationOverview:
        """Archive multiple notifications by ID.

        Args:
            notification_ids: List of notification PrefixedIDs.

        Returns:
            Updated NotificationOverview model.

        """
        from unraid_api.models import NotificationOverview

        mutation = """
            mutation ArchiveNotifications($ids: [PrefixedID!]!) {
                archiveNotifications(ids: $ids) {
                    unread { total info warning alert }
                    archive { total info warning alert }
                }
            }
        """
        result = await self.mutate(mutation, {"ids": notification_ids})
        return NotificationOverview(**(result.get("archiveNotifications") or {}))

    async def unarchive_notifications(
        self, notification_ids: list[str]
    ) -> NotificationOverview:
        """Unarchive multiple notifications by ID.

        Args:
            notification_ids: List of notification PrefixedIDs.

        Returns:
            Updated NotificationOverview model.

        """
        from unraid_api.models import NotificationOverview

        mutation = """
            mutation UnarchiveNotifications($ids: [PrefixedID!]!) {
                unarchiveNotifications(ids: $ids) {
                    unread { total info warning alert }
                    archive { total info warning alert }
                }
            }
        """
        result = await self.mutate(mutation, {"ids": notification_ids})
        return NotificationOverview(**(result.get("unarchiveNotifications") or {}))

    async def unarchive_all_notifications(
        self, importance: str | None = None
    ) -> NotificationOverview:
        """Unarchive all notifications (optionally filtered by importance).

        Args:
            importance: Optional importance filter (e.g., "ALERT", "WARNING", "INFO").

        Returns:
            Updated NotificationOverview model.

        """
        from unraid_api.models import NotificationOverview

        mutation = """
            mutation UnarchiveAll($importance: NotificationImportance) {
                unarchiveAll(importance: $importance) {
                    unread { total info warning alert }
                    archive { total info warning alert }
                }
            }
        """
        result = await self.mutate(mutation, {"importance": importance})
        return NotificationOverview(**(result.get("unarchiveAll") or {}))

    async def recalculate_notification_overview(
        self,
    ) -> NotificationOverview:
        """Recalculate notification counts overview.

        Returns:
            Updated NotificationOverview model.

        """
        from unraid_api.models import NotificationOverview

        mutation = """
            mutation {
                recalculateOverview {
                    unread { total info warning alert }
                    archive { total info warning alert }
                }
            }
        """
        result = await self.mutate(mutation)
        return NotificationOverview(**(result.get("recalculateOverview") or {}))

    # =========================================================================
    # Additional Subscriptions (Owner, Servers, Plugin Updates)
    # =========================================================================

    async def subscribe_owner(self) -> AsyncGenerator[Owner, None]:
        """Subscribe to server owner profile changes (username, avatar, url).

        Yields:
            Owner model on each update.

        """
        from unraid_api.models import Owner

        subscription = """
            subscription {
                ownerSubscription {
                    username avatar url
                }
            }
        """
        async for payload in self.subscribe(subscription):
            data = payload.get("ownerSubscription")
            if data:
                yield Owner(**data)

    async def subscribe_servers(self) -> AsyncGenerator[Server, None]:
        """Subscribe to server status and identity changes.

        Yields:
            Server model on each update.

        """
        from unraid_api.models import Server

        subscription = """
            subscription {
                serversSubscription {
                    id name guid lanip wanip localurl remoteurl status comment apikey
                    owner { id username avatar url }
                }
            }
        """
        async for payload in self.subscribe(subscription):
            data = payload.get("serversSubscription")
            if data:
                yield Server(**data)

    async def subscribe_plugin_install_updates(
        self, operation_id: str
    ) -> AsyncGenerator[PluginInstallEvent, None]:
        """Subscribe to real-time progress and logs for a plugin install operation.

        Args:
            operation_id: The ID of the plugin install operation to track.

        Yields:
            PluginInstallEvent model for each log line or state transition.

        """
        from unraid_api.models import PluginInstallEvent

        subscription = """
            subscription PluginInstallUpdates($operationId: ID!) {
                pluginInstallUpdates(operationId: $operationId) {
                    operationId status output timestamp
                }
            }
        """
        async for payload in self.subscribe(
            subscription, {"operationId": operation_id}
        ):
            data = payload.get("pluginInstallUpdates")
            if data:
                yield PluginInstallEvent(**data)
