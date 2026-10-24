"""Tests for UnraidClient async methods using aiointercept."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiointercept import CallbackResult, aiointercept

from unraid_api import UnraidClient
from unraid_api.capabilities import ServerCapabilities
from unraid_api.exceptions import (
    UnraidAPIError,
    UnraidAuthenticationError,
    UnraidConnectionError,
    UnraidSSLError,
    UnraidTimeoutError,
)


def create_ssl_error(
    host: str = "unraid.test", port: int = 443
) -> aiohttp.ClientSSLError:
    """Create a mock aiohttp SSL error for testing."""
    os_error = OSError(1, "certificate verify failed")

    class MockConnectionKey:
        pass

    mock_key = MockConnectionKey()
    mock_key.ssl = True  # type: ignore[attr-defined]
    mock_key.host = host  # type: ignore[attr-defined]
    mock_key.port = port  # type: ignore[attr-defined]
    mock_key.is_ssl = True  # type: ignore[attr-defined]

    return aiohttp.ClientSSLError(mock_key, os_error)


class TestClientContextManager:
    """Tests for async context manager."""

    async def test_context_manager_creates_session(self) -> None:
        """Test that context manager creates and closes session."""
        async with UnraidClient("unraid.test", "test-key") as client:
            assert client.session is not None
            assert client._owns_session is True

    async def test_context_manager_closes_session(self) -> None:
        """Test that context manager closes session on exit."""
        client = UnraidClient("unraid.test", "test-key")
        async with client:
            session = client.session
            assert session is not None
        assert client.session is None

    async def test_injected_session_not_closed(self) -> None:
        """Test that injected session is not closed by client."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.close = AsyncMock()

        client = UnraidClient("unraid.test", "test-key", session=mock_session)
        await client.close()

        # Should not close injected session
        mock_session.close.assert_not_called()


class TestClientSessionCreation:
    """Tests for session creation."""

    async def test_create_session_with_ssl_verification(self) -> None:
        """Test session creation with SSL verification enabled."""
        client = UnraidClient("unraid.test", "test-key", verify_ssl=True)
        await client._create_session()

        assert client.session is not None
        await client.close()

    async def test_create_session_without_ssl_verification(self) -> None:
        """Test session creation with SSL verification disabled."""
        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        await client._create_session()

        assert client.session is not None
        await client.close()

    async def test_create_session_idempotent(self) -> None:
        """Test that _create_session is idempotent."""
        client = UnraidClient("unraid.test", "test-key")
        await client._create_session()
        first_session = client.session

        await client._create_session()
        assert client.session is first_session

        await client.close()


class TestRedirectDiscovery:
    """Tests for URL redirect discovery."""

    async def test_discover_http_no_redirect(self) -> None:
        """Test discovery when server accepts HTTP (no SSL)."""
        async with aiointercept(mock_external_urls=True) as m:
            # GraphQL endpoint returns a non-redirect response (GET not supported)
            m.get(
                "http://unraid.test/graphql",
                status=400,
                body='{"errors":[{"message":"GET not supported"}]}',
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_http_no_redirect_status_200(self) -> None:
        """Test discovery when server returns 200 on HTTP (no SSL)."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=200)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_same_port_assumes_https(self) -> None:
        """Test that http_port == https_port skips probe and assumes HTTPS."""
        async with UnraidClient(
            "unraid.test",
            "test-key",
            http_port=4443,
            https_port=4443,
            verify_ssl=False,
        ) as client:
            redirect_url, use_ssl = await client._discover_redirect_url()

            assert redirect_url is None
            assert use_ssl is True

    async def test_discover_same_port_default_443(self) -> None:
        """Test that http_port == https_port == 443 assumes HTTPS."""
        async with UnraidClient(
            "unraid.test",
            "test-key",
            http_port=443,
            https_port=443,
            verify_ssl=False,
        ) as client:
            redirect_url, use_ssl = await client._discover_redirect_url()

            assert redirect_url is None
            assert use_ssl is True

    async def test_discover_nginx_400_https_port(self) -> None:
        """Test detection of nginx 400 'plain HTTP to HTTPS port' response."""
        nginx_body = (
            "<html>\n"
            "<head><title>400 The plain HTTP request was sent to HTTPS port"
            "</title></head>\n"
            "<body>\n"
            "<center><h1>400 Bad Request</h1></center>\n"
            "<center>The plain HTTP request was sent to HTTPS port</center>\n"
            "</body>\n"
            "</html>\n"
        )
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:8080/graphql",
                status=400,
                body=nginx_body,
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=8080,
                https_port=4443,
                verify_ssl=False,
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://unraid.test:8080/graphql"
                assert use_ssl is True

    async def test_discover_nginx_400_default_https_port(self) -> None:
        """Test nginx 400 on port 443 omits port suffix from HTTPS URL."""
        nginx_body = (
            "<html>\n"
            "<head><title>400 The plain HTTP request was sent to HTTPS port"
            "</title></head>\n"
            "<body>\n"
            "<center><h1>400 Bad Request</h1></center>\n"
            "<center>The plain HTTP request was sent to HTTPS port</center>\n"
            "</body>\n"
            "</html>\n"
        )
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:443/graphql",
                status=400,
                body=nginx_body,
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=443,
                https_port=8443,
                verify_ssl=False,
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://unraid.test/graphql"
                assert use_ssl is True

    async def test_discover_generic_400_is_http(self) -> None:
        """Test that a generic 400 (not nginx HTTPS error) means HTTP mode."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=400,
                body="Bad Request",
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_https_redirect(self) -> None:
        """Test discovery when server redirects to HTTPS."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://unraid.test/graphql"},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://unraid.test/graphql"
                assert use_ssl is True

    async def test_discover_https_redirect_with_port_443(self) -> None:
        """Test discovery normalizes redirect URL when port is 443."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://unraid.test:443/graphql"},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                # Port 443 should be normalized away
                assert redirect_url == "https://unraid.test/graphql"
                assert use_ssl is True

    async def test_discover_redirect_without_location_in_get(self) -> None:
        """Test discovery when redirect response has no Location header."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                # No Location header
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                # Falls through to "HTTP endpoint accessible"
                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_redirect_to_non_https(self) -> None:
        """Test discovery when redirect goes to non-HTTPS URL."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "http://other-host.local/graphql"},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                # Non-HTTPS, non-myunraid redirect falls through
                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_https_redirect_to_different_host_rejected(self) -> None:
        """SSRF guard: HTTPS redirect to a different hostname must be rejected.

        A malicious or misconfigured server should not be able to redirect the
        HTTP probe to an arbitrary HTTPS URL on a different host, which would
        cause subsequent requests (including the API key) to be sent there.
        """
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://evil.example.com/graphql"},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                # Redirect to a different host must be silently rejected
                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_https_redirect_same_host_accepted(self) -> None:
        """SSRF guard: HTTPS redirect to the same hostname must still work."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://unraid.test/graphql"},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://unraid.test/graphql"
                assert use_ssl is True

    async def test_discover_without_session(self) -> None:
        """Test discovery creates session if none exists."""
        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        assert client._session is None

        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=200,
            )

            redirect_url, use_ssl = await client._discover_redirect_url()

            assert redirect_url is None
            assert use_ssl is False
            assert client._session is not None

        await client.close()

    async def test_discover_myunraid_redirect(self) -> None:
        """Test discovery when server redirects to myunraid.net."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://myserver.myunraid.net/graphql"},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://myserver.myunraid.net/graphql"
                assert use_ssl is True

    async def test_discover_fallback_to_https_on_error_default_port(self) -> None:
        """Test discovery falls back to HTTPS on connection error with default port.

        When using the default HTTP port (80), a connection error should fall
        back to HTTPS — this is standard HTTP→HTTPS upgrade behavior.
        """
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                exception=True,
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url is None
                assert use_ssl is True

    async def test_discover_raises_on_error_custom_http_port(self) -> None:
        """Test discovery raises UnraidConnectionError when custom port is unreachable.

        When the user specifies a non-default http_port (e.g., 880) and that
        port is unreachable, the library should raise instead of silently
        falling back to HTTPS on port 443. See GitHub issue #9.
        """
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:880/graphql",
                exception=True,
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=880,
                verify_ssl=False,
            ) as client:
                with pytest.raises(UnraidConnectionError, match="port 880"):
                    await client._discover_redirect_url()

    async def test_discover_raises_on_timeout_custom_http_port(self) -> None:
        """Test discovery raises when custom port times out."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:8080/graphql",
                exception=True,
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=8080,
                verify_ssl=False,
            ) as client:
                with pytest.raises(UnraidConnectionError, match="port 8080"):
                    await client._discover_redirect_url()

    async def test_discover_custom_port_success_still_works(self) -> None:
        """Test that a custom port that actually works still functions.

        When the custom port is reachable and returns a valid HTTP response,
        normal redirect discovery should proceed as usual.
        """
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:880/graphql",
                status=302,
                headers={"Location": "https://unraid.test/graphql"},
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=880,
                verify_ssl=False,
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://unraid.test/graphql"
                assert use_ssl is True

    async def test_discover_custom_port_http_no_redirect(self) -> None:
        """Test that a reachable custom HTTP port with no redirect works."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:880/graphql",
                status=200,
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=880,
                verify_ssl=False,
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url is None
                assert use_ssl is False

    async def test_discover_fallback_to_https_on_ssl_error(self) -> None:
        """Test discovery falls back to HTTPS on SSL error (doesn't raise).

        Patches the session directly: aiointercept can only raise
        ClientConnectionError, but this test needs a real SSL error to
        exercise the SSL-specific discovery path.
        """
        ssl_error = create_ssl_error()

        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            assert client._session is not None
            with patch.object(client._session, "get", side_effect=ssl_error):
                # Discovery should catch SSL errors and fall back to HTTPS
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url is None
                assert use_ssl is True

    async def test_discover_ssl_error_custom_port_raises(self) -> None:
        """Test that SSL error on custom port raises instead of fallback."""
        ssl_error = create_ssl_error()

        async with UnraidClient(
            "unraid.test",
            "test-key",
            http_port=880,
            verify_ssl=False,
        ) as client:
            assert client._session is not None
            with (
                patch.object(client._session, "get", side_effect=ssl_error),
                pytest.raises(UnraidConnectionError, match="port 880"),
            ):
                await client._discover_redirect_url()

    async def test_discover_custom_http_and_https_ports_redirect(self) -> None:
        """Test custom HTTP + HTTPS ports with redirect works end-to-end.

        Simulates Unraid configured with HTTP on 8080 and HTTPS on 8443.
        The HTTP probe hits 8080, gets a redirect to https://host:8443/...,
        and the redirect URL is used directly.
        """
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:8080/graphql",
                status=302,
                headers={"Location": "https://unraid.test:8443/graphql"},
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=8080,
                https_port=8443,
                verify_ssl=False,
            ) as client:
                redirect_url, use_ssl = await client._discover_redirect_url()

                assert redirect_url == "https://unraid.test:8443/graphql"
                assert use_ssl is True

    async def test_discover_custom_http_and_https_ports_unreachable(self) -> None:
        """Test custom HTTP + HTTPS ports raises when HTTP port is unreachable.

        Simulates wrong ports: HTTP on 8080 is unreachable. Should raise
        immediately instead of silently falling back to HTTPS on 8443.
        """
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test:8080/graphql",
                exception=True,
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                http_port=8080,
                https_port=8443,
                verify_ssl=False,
            ) as client:
                with pytest.raises(UnraidConnectionError, match="port 8080"):
                    await client._discover_redirect_url()


class TestGraphQLQuery:
    """Tests for GraphQL query execution."""

    async def test_query_success(self) -> None:
        """Test successful GraphQL query."""
        async with aiointercept(mock_external_urls=True) as m:
            # Mock redirect discovery
            m.get("http://unraid.test/graphql", status=400)
            # Mock GraphQL query
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.query("query { online }")

                assert result == {"online": True}

    async def test_query_with_variables(self) -> None:
        """Test GraphQL query with variables."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {"start": {"id": "container:123", "state": "RUNNING"}}
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                mutation = """
                    mutation StartContainer($id: PrefixedID!) {
                        docker { start(id: $id) { id state } }
                    }
                """
                result = await client.query(
                    mutation,
                    variables={"id": "container:123"},
                )

                assert result["docker"]["start"]["state"] == "RUNNING"

    async def test_query_with_graphql_errors_and_data(self) -> None:
        """Test query that returns partial data with errors."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {"array": {"state": "STARTED"}},
                    "errors": [{"message": "UPS not configured"}],
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                # Should return data despite errors
                result = await client.query("query { array { state } ups { status } }")

                assert result == {"array": {"state": "STARTED"}}

    async def test_query_with_graphql_errors_no_data(self) -> None:
        """Test query that returns only errors."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {},
                    "errors": [{"message": "Unauthorized", "path": ["query"]}],
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidAPIError) as exc_info:
                    await client.query("query { secret }")

                assert "GraphQL query failed" in str(exc_info.value)

    async def test_query_authentication_error(self) -> None:
        """Test query with authentication failure."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", status=401)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidAuthenticationError):
                    await client.query("query { online }")

    async def test_query_forbidden_error(self) -> None:
        """Test query with forbidden response."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", status=403)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidAuthenticationError):
                    await client.query("query { online }")

    async def test_query_connection_error(self) -> None:
        """Test query with connection failure."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                exception=True,
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidConnectionError):
                    await client.query("query { online }")

    async def test_query_timeout_error(self) -> None:
        """Test query with timeout.

        Patches the session directly: aiointercept can only raise
        ClientConnectionError, but this test needs a real TimeoutError to
        exercise the timeout-wrapping path.
        """
        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            client._resolved_url = "http://unraid.test/graphql"
            assert client._session is not None
            with (
                patch.object(
                    client._session,
                    "post",
                    side_effect=TimeoutError("Request timed out"),
                ),
                pytest.raises(UnraidTimeoutError),
            ):
                await client.query("query { online }")

    async def test_query_ssl_error(self) -> None:
        """Test query with SSL certificate error."""
        ssl_error = create_ssl_error()

        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            client._resolved_url = "http://unraid.test/graphql"
            assert client._session is not None
            with patch.object(client._session, "post", side_effect=ssl_error):
                with pytest.raises(UnraidSSLError) as exc_info:
                    await client.query("query { online }")

                assert "SSL" in str(exc_info.value)

    async def test_ssl_error_is_catchable_as_connection_error(self) -> None:
        """Test that UnraidSSLError can be caught as UnraidConnectionError."""
        ssl_error = create_ssl_error()

        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            client._resolved_url = "http://unraid.test/graphql"
            assert client._session is not None
            with patch.object(client._session, "post", side_effect=ssl_error):
                # Should be catchable as UnraidConnectionError for backwards compat
                with pytest.raises(UnraidConnectionError) as exc_info:
                    await client.query("query { online }")

                # But should actually be UnraidSSLError
                assert isinstance(exc_info.value, UnraidSSLError)


class TestMutate:
    """Tests for GraphQL mutation execution."""

    async def test_mutate_calls_query(self) -> None:
        """Test that mutate delegates to query."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {"docker": {"start": {"id": "c:1", "state": "RUNNING"}}}
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.mutate(
                    "mutation { docker { start(id: $id) { id state } } }",
                    {"id": "c:1"},
                )

                assert result["docker"]["start"]["state"] == "RUNNING"


class TestConnectionMethods:
    """Tests for connection-related methods."""

    async def test_test_connection_success(self) -> None:
        """Test successful connection test."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.test_connection()

                assert result is True

    async def test_test_connection_offline(self) -> None:
        """Test connection test when server reports offline."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"online": False}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.test_connection()

                assert result is False

    async def test_get_version(self) -> None:
        """Test getting version information."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "versions": {
                                "core": {
                                    "unraid": "7.2.0",
                                    "api": "4.21.0",
                                }
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_version()

                assert result.unraid == "7.2.0"
                assert result.api == "4.21.0"


class TestContainerMethods:
    """Tests for Docker container methods."""

    async def test_start_container(self) -> None:
        """Test starting a Docker container."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "start": {
                                "id": "container:plex",
                                "state": "RUNNING",
                                "status": "Up 5 seconds",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.start_container("container:plex")

                assert result["docker"]["start"]["state"] == "RUNNING"

    async def test_stop_container(self) -> None:
        """Test stopping a Docker container."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "stop": {
                                "id": "container:plex",
                                "state": "EXITED",
                                "status": "Exited (0)",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.stop_container("container:plex")

                assert result["docker"]["stop"]["state"] == "EXITED"


class TestVmMethods:
    """Tests for VM methods."""

    async def test_start_vm(self) -> None:
        """Test starting a VM."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"start": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.start_vm("vm:windows")

                assert result["vm"]["start"] is True

    async def test_stop_vm(self) -> None:
        """Test stopping a VM."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"stop": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.stop_vm("vm:windows")

                assert result["vm"]["stop"] is True


class TestArrayMethods:
    """Tests for array control methods."""

    async def test_start_array(self) -> None:
        """Test starting the array."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {"setState": {"id": "array:1", "state": "STARTED"}}
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.start_array()

                assert result["array"]["setState"]["state"] == "STARTED"

    async def test_stop_array(self) -> None:
        """Test stopping the array."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {"setState": {"id": "array:1", "state": "STOPPED"}}
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.stop_array()

                assert result["array"]["setState"]["state"] == "STOPPED"


class TestParityMethods:
    """Tests for parity check methods."""

    async def test_start_parity_check(self) -> None:
        """Test starting parity check."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"parityCheck": {"start": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.start_parity_check()

                assert result["parityCheck"]["start"] is True

    async def test_start_parity_check_with_correction(self) -> None:
        """Test starting parity check with correction enabled."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"parityCheck": {"start": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.start_parity_check(correct=True)

                assert result["parityCheck"]["start"] is True

    async def test_pause_parity_check(self) -> None:
        """Test pausing parity check."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"parityCheck": {"pause": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.pause_parity_check()

                assert result["parityCheck"]["pause"] is True

    async def test_resume_parity_check(self) -> None:
        """Test resuming parity check."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"parityCheck": {"resume": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.resume_parity_check()

                assert result["parityCheck"]["resume"] is True

    async def test_cancel_parity_check(self) -> None:
        """Test canceling parity check."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"parityCheck": {"cancel": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.cancel_parity_check()

                assert result["parityCheck"]["cancel"] is True


class TestDiskSpinMethods:
    """Tests for disk spin control methods."""

    async def test_spin_up_disk(self) -> None:
        """Test spinning up a disk."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "mountArrayDisk": {"id": "disk:1", "isSpinning": True}
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.spin_up_disk("disk:1")

                assert result["array"]["mountArrayDisk"]["isSpinning"] is True

    async def test_spin_down_disk(self) -> None:
        """Test spinning down a disk."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "unmountArrayDisk": {"id": "disk:1", "isSpinning": False}
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.spin_down_disk("disk:1")

                assert result["array"]["unmountArrayDisk"]["isSpinning"] is False


class TestRedirectFollowing:
    """Tests for redirect following during requests."""

    async def test_follows_redirect_on_post(self) -> None:
        """Test that POST requests follow redirects."""
        async with aiointercept(mock_external_urls=True) as m:
            # Discovery finds HTTP works
            m.get("http://unraid.test/graphql", status=400)
            # First POST gets redirect
            m.post(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://unraid.test/graphql"},
            )
            # Follow redirect
            m.post(
                "https://unraid.test/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.query("query { online }")

                assert result == {"online": True}


class TestAdditionalContainerMethods:
    """Tests for additional Docker container methods."""

    async def test_pause_container(self) -> None:
        """Test pausing a container."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "pause": {
                                "id": "container:abc123",
                                "state": "paused",
                                "status": "Paused",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.pause_container("container:abc123")

                assert result["docker"]["pause"]["state"] == "paused"

    async def test_unpause_container(self) -> None:
        """Test unpausing a container."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "unpause": {
                                "id": "container:abc123",
                                "state": "running",
                                "status": "Up 5 days",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.unpause_container("container:abc123")

                assert result["docker"]["unpause"]["state"] == "running"

    async def test_update_container(self) -> None:
        """Test updating a container."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "updateContainer": {
                                "id": "container:abc123",
                                "names": ["/plex"],
                                "image": "plex:latest",
                                "state": "running",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.update_container("container:abc123")

                assert result["docker"]["updateContainer"]["image"] == "plex:latest"

    async def test_get_containers(self) -> None:
        """Test getting all containers."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plex:latest",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "ports": [],
                                    "isUpdateAvailable": False,
                                    "isOrphaned": False,
                                    "webUiUrl": "http://unraid.test:32400",
                                    "iconUrl": "/plugins/plex/icon.png",
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_containers()

                assert len(result) == 1
                assert result[0]["id"] == "container:abc123"
                assert result[0]["state"] == "running"


class TestAdditionalVmMethods:
    """Tests for additional VM methods."""

    async def test_pause_vm(self) -> None:
        """Test pausing a VM."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"pause": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.pause_vm("vm:windows10")

                assert result["vm"]["pause"] is True

    async def test_resume_vm(self) -> None:
        """Test resuming a VM."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"resume": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.resume_vm("vm:windows10")

                assert result["vm"]["resume"] is True

    async def test_force_stop_vm(self) -> None:
        """Test force stopping a VM."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"forceStop": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.force_stop_vm("vm:windows10")

                assert result["vm"]["forceStop"] is True

    async def test_reboot_vm(self) -> None:
        """Test rebooting a VM."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"reboot": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.reboot_vm("vm:windows10")

                assert result["vm"]["reboot"] is True

    async def test_get_vms(self) -> None:
        """Test getting all VMs."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "vms": {
                            "domains": [
                                {
                                    "id": "vm:windows10",
                                    "name": "Windows 10",
                                    "state": "running",
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_vms()

                assert len(result) == 1
                assert result[0]["name"] == "Windows 10"


class TestMetricsMethods:
    """Tests for system metrics methods."""

    async def test_get_metrics(self) -> None:
        """Test getting system metrics."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {
                                "percentTotal": 15.5,
                                "cpus": [
                                    {
                                        "percentTotal": 20.0,
                                        "percentUser": 10.0,
                                        "percentSystem": 5.0,
                                        "percentIdle": 80.0,
                                    }
                                ],
                            },
                            "memory": {
                                "total": 17179869184,
                                "used": 8589934592,
                                "free": 4294967296,
                                "available": 8589934592,
                                "percentTotal": 50.0,
                                "swapTotal": 0,
                                "swapUsed": 0,
                                "swapFree": 0,
                                "percentSwapTotal": 0.0,
                            },
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_metrics()

                assert result["cpu"]["percentTotal"] == 15.5
                assert result["memory"]["percentTotal"] == 50.0

    async def test_get_system_info(self) -> None:
        """Test getting system info."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "time": "2024-01-15T12:00:00Z",
                            "os": {
                                "hostname": "Tower",
                                "uptime": 1000000,
                                "kernel": "6.1.38-Unraid",
                                "platform": "linux",
                                "distro": "Unraid",
                                "arch": "x64",
                            },
                            "cpu": {
                                "manufacturer": "Intel",
                                "brand": "Core i7-12700K",
                                "cores": 12,
                                "threads": 20,
                                "speed": 3.60,
                            },
                            "memory": {"layout": []},
                            "versions": {
                                "core": {
                                    "unraid": "7.1.4",
                                    "api": "4.29.2",
                                    "kernel": "6.1.38-Unraid",
                                },
                                "packages": {
                                    "docker": "24.0.7",
                                    "openssl": "3.1.4",
                                    "node": "18.19.0",
                                },
                            },
                            "baseboard": {
                                "manufacturer": "ASUS",
                                "model": "Z690",
                                "memMax": 128,
                                "memSlots": 4,
                            },
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_system_info()

                assert result["os"]["hostname"] == "Tower"
                assert result["versions"]["core"]["unraid"] == "7.1.4"


class TestArrayStatusMethod:
    """Tests for array status method."""

    async def test_get_array_status(self) -> None:
        """Test getting comprehensive array status."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "state": "STARTED",
                            "capacity": {
                                "kilobytes": {
                                    "free": 1000000,
                                    "used": 500000,
                                    "total": 1500000,
                                },
                                "disks": {"free": 5, "used": 3, "total": 8},
                            },
                            "parityCheckStatus": {
                                "status": "IDLE",
                                "progress": 0,
                                "running": False,
                                "paused": False,
                                "errors": 0,
                                "speed": 0,
                            },
                            "boot": {
                                "id": "boot:0",
                                "name": "boot",
                                "device": "sda",
                                "size": 32000000,
                                "temp": None,
                                "type": "Flash",
                            },
                            "parities": [
                                {
                                    "id": "parity:0",
                                    "name": "Parity",
                                    "device": "sdb",
                                    "size": 4000000000,
                                    "status": "DISK_OK",
                                    "type": "Parity",
                                    "temp": 35,
                                    "numReads": 1000,
                                    "numWrites": 500,
                                    "numErrors": 0,
                                }
                            ],
                            "disks": [
                                {
                                    "id": "disk:1",
                                    "name": "Disk 1",
                                    "device": "sdc",
                                    "size": 4000000000,
                                    "status": "DISK_OK",
                                    "type": "Data",
                                    "temp": 32,
                                    "fsSize": 3900000000,
                                    "fsFree": 1000000000,
                                    "fsUsed": 2900000000,
                                    "numReads": 5000,
                                    "numWrites": 3000,
                                    "numErrors": 0,
                                    "isSpinning": True,
                                }
                            ],
                            "caches": [],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_array_status()

                assert result["state"] == "STARTED"
                assert len(result["disks"]) == 1
                assert result["disks"][0]["name"] == "Disk 1"


class TestSharesMethod:
    """Tests for shares method."""

    async def test_get_shares(self) -> None:
        """Test getting all shares."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "shares": [
                            {
                                "id": "share:appdata",
                                "name": "appdata",
                                "free": 1000000,
                                "used": 500000,
                                "size": 1500000,
                                "cache": "yes",
                                "comment": "Application data",
                                "include": "",
                                "exclude": "",
                            },
                            {
                                "id": "share:media",
                                "name": "media",
                                "free": 2000000,
                                "used": 8000000,
                                "size": 10000000,
                                "cache": "no",
                                "comment": "Media files",
                                "include": "",
                                "exclude": "",
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_shares()

                assert len(result) == 2
                assert result[0]["name"] == "appdata"
                assert result[1]["name"] == "media"


class TestUpsMethod:
    """Tests for UPS method."""

    async def test_get_ups_status(self) -> None:
        """Test getting UPS status."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "upsDevices": [
                            {
                                "id": "ups:0",
                                "name": "CyberPower CP1500",
                                "model": "CP1500PFCLCD",
                                "status": "OL",
                                "battery": {
                                    "chargeLevel": 100,
                                    "estimatedRuntime": 1800,
                                    "health": "GOOD",
                                },
                                "power": {
                                    "inputVoltage": 120.0,
                                    "outputVoltage": 120.0,
                                    "loadPercentage": 25.0,
                                    "nominalPower": 1500,
                                    "currentPower": 375.0,
                                },
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_ups_status()

                assert len(result) == 1
                assert result[0]["name"] == "CyberPower CP1500"
                assert result[0]["battery"]["chargeLevel"] == 100
                assert result[0]["power"]["nominalPower"] == 1500
                assert result[0]["power"]["currentPower"] == 375.0


class TestNotificationsMethod:
    """Tests for notifications method."""

    async def test_get_notifications(self) -> None:
        """Test getting notifications."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "notifications": {
                            "overview": {
                                "unread": {
                                    "info": 5,
                                    "warning": 2,
                                    "alert": 0,
                                    "total": 7,
                                },
                                "archive": {
                                    "info": 100,
                                    "warning": 20,
                                    "alert": 5,
                                    "total": 125,
                                },
                            },
                            "list": [
                                {
                                    "id": "notif:1",
                                    "title": "Array Started",
                                    "subject": "Array",
                                    "description": "Array started",
                                    "importance": "INFO",
                                    "timestamp": "2024-01-15T12:00:00Z",
                                },
                                {
                                    "id": "notif:2",
                                    "title": "Disk Warning",
                                    "subject": "Disk 1",
                                    "description": "Disk 1 temperature is high",
                                    "importance": "WARNING",
                                    "timestamp": "2024-01-15T11:00:00Z",
                                },
                            ],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_notifications()

                assert result["overview"]["unread"]["total"] == 7
                assert len(result["list"]) == 2
                assert result["list"][0]["title"] == "Array Started"

    async def test_get_notifications_with_params(self) -> None:
        """Test getting notifications with parameters."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "notifications": {
                            "overview": {
                                "unread": {
                                    "info": 0,
                                    "warning": 0,
                                    "alert": 0,
                                    "total": 0,
                                },
                                "archive": {
                                    "info": 100,
                                    "warning": 20,
                                    "alert": 5,
                                    "total": 125,
                                },
                            },
                            "list": [],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_notifications(
                    notification_type="ARCHIVE", limit=10, offset=0
                )

                assert result["overview"]["archive"]["total"] == 125


class TestEdgeCases:
    """Tests for edge cases and defensive code paths."""

    async def test_redirect_without_location_header(self) -> None:
        """Test handling of redirect response without Location header."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                status=302,
                # No Location header
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidConnectionError) as exc_info:
                    await client.query("query { online }")
                assert "Redirect" in str(exc_info.value)
                assert "without Location header" in str(exc_info.value)

    async def test_graphql_error_with_path(self) -> None:
        """Test GraphQL error with path information."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": None,
                    "errors": [
                        {
                            "message": "Cannot query field 'invalid'",
                            "path": ["query", "invalid"],
                        }
                    ],
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidAPIError) as exc_info:
                    await client.query("query { invalid }")
                assert "Cannot query field" in str(exc_info.value)

    async def test_use_https_when_discovery_fails(self) -> None:
        """Test that HTTPS is used when HTTP discovery fails."""
        async with aiointercept(mock_external_urls=True) as m:
            # HTTP fails completely
            m.get(
                "http://unraid.test/graphql",
                exception=True,
            )
            # HTTPS works
            m.post(
                "https://unraid.test/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.query("query { online }")
                assert result == {"online": True}

    async def test_custom_https_port_in_url(self) -> None:
        """Test that custom HTTPS port is included in URL."""
        async with aiointercept(mock_external_urls=True) as m:
            # HTTP fails
            m.get(
                "http://unraid.test/graphql",
                exception=True,
            )
            # HTTPS on custom port works
            m.post(
                "https://unraid.test:8443/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test",
                "test-key",
                https_port=8443,
                verify_ssl=False,
            ) as client:
                result = await client.query("query { online }")
                assert result == {"online": True}

    async def test_discover_raises_if_session_creation_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _discover_redirect_url raises if session stays None."""
        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)

        monkeypatch.setattr(client, "_create_session", AsyncMock())

        with pytest.raises(
            UnraidConnectionError, match="Failed to create HTTP session"
        ):
            await client._discover_redirect_url()

    async def test_make_request_raises_if_session_creation_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _make_request raises if session stays None."""
        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)

        monkeypatch.setattr(client, "_create_session", AsyncMock())

        with pytest.raises(
            UnraidConnectionError, match="Failed to create HTTP session"
        ):
            await client._make_request({"query": "query { online }"})

    async def test_make_request_skips_discovery_when_url_resolved(self) -> None:
        """Test _make_request skips discovery when URL already resolved."""
        async with aiointercept(mock_external_urls=True) as m:
            # Only mock the POST, no GET needed since URL is pre-resolved
            m.post(
                "https://unraid.test/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                # Pre-set resolved URL to skip discovery
                client._resolved_url = "https://unraid.test/graphql"
                result = await client.query("query { online }")

                assert result == {"online": True}

    async def test_make_request_creates_session_if_none(self) -> None:
        """Test that _make_request creates session if none exists."""
        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        assert client._session is None

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=200)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"online": True}},
            )

            result = await client.query("query { online }")
            assert result == {"online": True}
            assert client._session is not None

        await client.close()

    async def test_make_request_uses_redirect_url_from_discovery(self) -> None:
        """Test that _make_request uses redirect URL from discovery."""
        async with aiointercept(mock_external_urls=True) as m:
            # Redirect to myunraid.net (Strict mode)
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://myserver.myunraid.net/graphql"},
            )
            m.post(
                "https://myserver.myunraid.net/graphql",
                payload={"data": {"online": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.query("query { online }")

                assert result == {"online": True}
                assert client._resolved_url == "https://myserver.myunraid.net/graphql"

    async def test_query_with_non_dict_error_items(self) -> None:
        """Test query handles non-dict error items in GraphQL response."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {},
                    "errors": ["Simple string error", "Another error"],
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidAPIError) as exc_info:
                    await client.query("query { invalid }")

                assert "Simple string error" in str(exc_info.value)

    async def test_partial_failure_returns_data(self) -> None:
        """Test that partial failures return data with errors logged."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {"online": True, "someField": None},
                    "errors": [
                        {"message": "someField is deprecated"},
                    ],
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.query("query { online someField }")
                # Data is returned despite errors
                assert result["online"] is True


class TestRemoveContainerMethod:
    """Tests for remove container method."""

    async def test_remove_container(self) -> None:
        """Test removing a container."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"docker": {"removeContainer": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.remove_container("container:abc123")

                assert result["docker"]["removeContainer"] is True

    async def test_remove_container_with_image(self) -> None:
        """Test removing a container with its image."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"docker": {"removeContainer": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.remove_container(
                    "container:abc123", with_image=True
                )

                assert result["docker"]["removeContainer"] is True


class TestDisksMethod:
    """Tests for physical disks method."""

    async def test_get_disks(self) -> None:
        """Test getting physical disks."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "disks": [
                            {
                                "id": "disk:sda",
                                "device": "/dev/sda",
                                "name": "Samsung SSD 870 EVO",
                                "vendor": "Samsung",
                                "size": 500107862016,
                                "type": "SSD",
                                "interfaceType": "SATA",
                                "smartStatus": "OK",
                                "temperature": 32,
                                "isSpinning": False,
                                "partitions": [
                                    {
                                        "name": "sda1",
                                        "fsType": "XFS",
                                        "size": 500000000000,
                                    }
                                ],
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_disks()

                assert len(result) == 1
                assert result[0]["name"] == "Samsung SSD 870 EVO"


class TestParityHistoryMethod:
    """Tests for parity history method."""

    async def test_get_parity_history(self) -> None:
        """Test getting parity check history."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "parityHistory": [
                            {
                                "date": "2024-01-15",
                                "duration": 36000,
                                "speed": 150000000,
                                "status": "COMPLETED",
                                "errors": 0,
                            },
                            {
                                "date": "2024-01-01",
                                "duration": 35500,
                                "speed": 155000000,
                                "status": "COMPLETED",
                                "errors": 0,
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_parity_history()

                assert len(result) == 2
                assert result[0].status == "COMPLETED"
                assert result[0].errors == 0


class TestGetServerInfoMethod:
    """Tests for get_server_info method."""

    async def test_get_server_info(self) -> None:
        """Test getting server info returns ServerInfo model."""
        from unraid_api.models import ServerInfo

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "system": {
                                "uuid": "abc123-def456",
                                "manufacturer": "Dell Inc.",
                                "model": "PowerEdge R730",
                                "serial": "SYS123",
                            },
                            "baseboard": {
                                "manufacturer": "Dell",
                                "model": "0HFG24",
                                "serial": "BB456",
                            },
                            "os": {
                                "hostname": "Tower",
                                "distro": "Unraid",
                                "release": "7.2.0",
                                "kernel": "6.1.38-Unraid",
                                "arch": "x64",
                            },
                            "cpu": {
                                "manufacturer": "Intel",
                                "brand": "Intel Xeon E5-2680",
                                "cores": 12,
                                "threads": 24,
                            },
                            "versions": {
                                "core": {
                                    "unraid": "7.2.0",
                                    "api": "4.29.2",
                                }
                            },
                        },
                        "server": {
                            "lanip": "unraid.test",
                            "localurl": "http://unraid.test",
                            "remoteurl": "https://myserver.myunraid.net",
                        },
                        "registration": {
                            "type": "Pro",
                            "state": "valid",
                        },
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_server_info()

                # Check it returns a ServerInfo instance
                assert isinstance(result, ServerInfo)

                # Verify fields
                assert result.uuid == "abc123-def456"
                assert result.hostname == "Tower"
                assert result.manufacturer == "Lime Technology"
                assert result.model == "Unraid 7.2.0"
                assert result.sw_version == "7.2.0"
                assert result.hw_version == "6.1.38-Unraid"
                assert result.serial_number == "SYS123"
                assert result.hw_manufacturer == "Dell Inc."
                assert result.hw_model == "PowerEdge R730"
                assert result.api_version == "4.29.2"
                assert result.lan_ip == "unraid.test"
                assert result.local_url == "http://unraid.test"
                assert result.remote_url == "https://myserver.myunraid.net"
                assert result.license_type == "Pro"
                assert result.license_state == "valid"
                assert result.cpu_brand == "Intel Xeon E5-2680"
                assert result.cpu_cores == 12
                assert result.cpu_threads == 24

    async def test_get_server_info_with_baseboard_fallback(self) -> None:
        """Test server info falls back to baseboard when system info missing."""
        from unraid_api.models import ServerInfo

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "system": {
                                "uuid": "abc123",
                                "manufacturer": None,
                                "model": None,
                                "serial": None,
                            },
                            "baseboard": {
                                "manufacturer": "ASUS",
                                "model": "Z690",
                                "serial": "BBSERIAL123",
                            },
                            "os": {
                                "hostname": "MyTower",
                                "distro": "Unraid",
                                "release": "7.1.4",
                                "kernel": "6.1.38-Unraid",
                                "arch": "x64",
                            },
                            "cpu": {
                                "brand": "Intel Core i7-12700K",
                                "cores": 12,
                                "threads": 20,
                            },
                            "versions": {
                                "core": {
                                    "unraid": "7.1.4",
                                    "api": "4.21.0",
                                }
                            },
                        },
                        "server": {
                            "lanip": "192.168.1.50",
                        },
                        "registration": {
                            "type": "Basic",
                            "state": "valid",
                        },
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_server_info()

                assert isinstance(result, ServerInfo)
                assert result.hw_manufacturer == "ASUS"
                assert result.hw_model == "Z690"
                assert result.serial_number == "BBSERIAL123"

    async def test_get_server_info_minimal_response(self) -> None:
        """Test server info with minimal data in response."""
        from unraid_api.models import ServerInfo

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "system": {"uuid": "min-uuid"},
                            "baseboard": {},
                            "os": {"hostname": "MinimalServer"},
                            "cpu": {},
                            "versions": {
                                "core": {
                                    "unraid": "7.0.0",
                                }
                            },
                        },
                        "server": {},
                        "registration": {},
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_server_info()

                assert isinstance(result, ServerInfo)
                assert result.uuid == "min-uuid"
                assert result.hostname == "MinimalServer"
                assert result.model == "Unraid 7.0.0"
                assert result.lan_ip is None
                assert result.license_type is None


class TestGetSystemMetricsMethod:
    """Tests for get_system_metrics method (returns SystemMetrics model)."""

    async def test_get_system_metrics(self) -> None:
        """Test getting system metrics returns SystemMetrics model."""
        from unraid_api.models import SystemMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {"percentTotal": 25.5},
                            "memory": {
                                "total": 34359738368,
                                "used": 17179869184,
                                "free": 17179869184,
                                "available": 25769803776,
                                "percentTotal": 50.0,
                                "swapTotal": 8589934592,
                                "swapUsed": 0,
                                "percentSwapTotal": 0.0,
                            },
                        },
                        "info": {
                            "os": {"uptime": "2024-01-15T10:30:00Z"},
                        },
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_system_metrics()

                assert isinstance(result, SystemMetrics)
                assert result.cpu_percent == 25.5
                assert result.memory_percent == 50.0
                assert result.memory_total == 34359738368
                assert result.memory_used == 17179869184
                assert result.memory_available == 25769803776
                assert result.swap_percent == 0.0
                assert result.uptime is not None

    async def test_get_system_metrics_minimal_response(self) -> None:
        """Test system metrics with minimal response data."""
        from unraid_api.models import SystemMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {"percentTotal": 10.0},
                            "memory": {"percentTotal": 30.0},
                        },
                        "info": {"os": {}},
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_system_metrics()

                assert isinstance(result, SystemMetrics)
                assert result.cpu_percent == 10.0
                assert result.memory_percent == 30.0
                assert result.uptime is None


class TestGetSystemMetricsSafeMethod:
    """Tests for get_system_metrics_safe method (omits temperature sensors)."""

    async def test_get_system_metrics_safe(self) -> None:
        """Test safe system metrics returns SystemMetrics without temperature."""
        from unraid_api.models import SystemMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {"percentTotal": 25.5},
                            "memory": {
                                "total": 34359738368,
                                "used": 17179869184,
                                "free": 17179869184,
                                "available": 25769803776,
                                "active": 8589934592,
                                "buffcache": 4294967296,
                                "percentTotal": 50.0,
                                "swapTotal": 8589934592,
                                "swapUsed": 0,
                                "swapFree": 8589934592,
                                "percentSwapTotal": 0.0,
                            },
                        },
                        "info": {
                            "os": {"uptime": "2024-01-15T10:30:00Z"},
                            "cpu": {"packages": {"temp": [55.0], "totalPower": 65.0}},
                        },
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_system_metrics_safe()

                assert isinstance(result, SystemMetrics)
                assert result.cpu_percent == 25.5
                assert result.memory_percent == 50.0
                assert result.memory_total == 34359738368
                assert result.memory_used == 17179869184
                assert result.memory_available == 25769803776
                assert result.swap_percent == 0.0
                assert result.swap_total == 8589934592
                assert result.swap_used == 0
                assert result.swap_free == 8589934592
                assert result.temperature is None
                assert result.cpu_temperature == 55.0
                assert result.cpu_power == 65.0
                assert result.uptime is not None

    async def test_get_system_metrics_safe_minimal_response(self) -> None:
        """Test safe system metrics with minimal response data."""
        from unraid_api.models import SystemMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {"percentTotal": 10.0},
                            "memory": {"percentTotal": 30.0},
                        },
                        "info": {"os": {}},
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_system_metrics_safe()

                assert isinstance(result, SystemMetrics)
                assert result.cpu_percent == 10.0
                assert result.memory_percent == 30.0
                assert result.temperature is None
                assert result.cpu_temperature is None
                assert result.uptime is None


class TestTypedGetContainersMethod:
    """Tests for typed_get_containers method (returns list[DockerContainer])."""

    async def test_typed_get_containers(self) -> None:
        """Test getting containers returns list of DockerContainer models."""
        from unraid_api.models import DockerContainer

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "ports": [
                                        {
                                            "ip": "unraid.test",
                                            "privatePort": 32400,
                                            "publicPort": 32400,
                                            "type": "tcp",
                                        }
                                    ],
                                },
                                {
                                    "id": "container:def456",
                                    "names": ["/sonarr"],
                                    "image": "linuxserver/sonarr",
                                    "state": "stopped",
                                    "status": "Exited (0) 2 hours ago",
                                    "autoStart": False,
                                    "ports": [],
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers()

                assert isinstance(result, list)
                assert len(result) == 2
                assert all(isinstance(c, DockerContainer) for c in result)
                assert result[0].id == "container:abc123"
                assert result[0].name == "plex"
                assert result[0].state == "running"
                assert result[0].image == "plexinc/pms-docker"
                assert len(result[0].ports) == 1
                assert result[1].id == "container:def456"
                assert result[1].name == "sonarr"
                assert result[1].state == "stopped"

    async def test_typed_get_containers_empty(self) -> None:
        """Test getting containers returns empty list when none exist."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"docker": {"containers": []}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers()

                assert isinstance(result, list)
                assert len(result) == 0

    async def test_typed_get_containers_fallback_on_unsupported_fields(self) -> None:
        """Test fallback to core query when extended fields are unsupported."""
        from unraid_api.models import DockerContainer

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            # First POST (extended query) returns 400
            m.post("http://unraid.test/graphql", status=400)
            # Second POST (core fallback query) succeeds
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "ports": [],
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_containers()

                assert len(result) == 1
                assert isinstance(result[0], DockerContainer)
                assert result[0].name == "plex"
                # Extended fields should be None in fallback
                assert result[0].isUpdateAvailable is None
                assert result[0].webUiUrl is None
                assert result[0].iconUrl is None

    async def test_typed_get_containers_with_extended_fields(self) -> None:
        """Test extended fields are populated when server supports them."""
        from unraid_api.models import DockerContainer

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "isUpdateAvailable": True,
                                    "webUiUrl": "http://unraid.test:32400",
                                    "iconUrl": "/icons/plex.png",
                                    "ports": [],
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers()

                assert len(result) == 1
                assert isinstance(result[0], DockerContainer)
                assert result[0].isUpdateAvailable is True
                assert result[0].webUiUrl == "http://unraid.test:32400"
                assert result[0].iconUrl == "/icons/plex.png"

    async def test_typed_get_containers_auth_error_not_swallowed(self) -> None:
        """Test that auth errors are re-raised, not caught by fallback."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            # Extended query returns 401 (auth error)
            m.post("http://unraid.test/graphql", status=401)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidAuthenticationError):
                    await client.typed_get_containers()

    async def test_typed_get_containers_populates_full_tailscale_status(
        self,
    ) -> None:
        """Extended query must request and parse every TailscaleStatus field.

        HA integrations need key-expiry warnings, update-available status,
        exit-node configuration, and the assigned tailnet IPs — all of
        which live on TailscaleStatus but were previously truncated.
        """
        from unraid_api.models import DockerContainer

        payload_ts = {
            "hostname": "plex",
            "dnsName": "plex.tail12345.ts.net.",
            "online": True,
            "version": "1.80.0",
            "latestVersion": "1.82.5",
            "updateAvailable": True,
            "relay": "sea",
            "relayName": "Seattle",
            "tailscaleIps": ["100.64.0.2", "fd7a:115c:a1e0::2"],
            "primaryRoutes": ["10.0.0.0/24"],
            "isExitNode": False,
            "exitNodeStatus": {
                "online": True,
                "tailscaleIps": ["100.64.0.3"],
            },
            "webUiUrl": "http://100.64.0.2:32400",
            "keyExpiry": "2026-10-01T12:00:00Z",
            "keyExpiryDays": 42,
            "keyExpired": False,
            "backendState": "Running",
            "authUrl": None,
        }

        captured_requests: list[str] = []

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            body = kwargs.get("json") or {}
            captured_requests.append(body.get("query", ""))
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "ports": [],
                                    "tailscaleStatus": payload_ts,
                                },
                            ]
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers()

        assert captured_requests, "no GraphQL request was captured"
        query = captured_requests[0]
        for needed in (
            "version",
            "latestVersion",
            "updateAvailable",
            "relay",
            "relayName",
            "tailscaleIps",
            "primaryRoutes",
            "isExitNode",
            "exitNodeStatus",
            "keyExpiry",
            "keyExpiryDays",
            "keyExpired",
            "backendState",
            "authUrl",
        ):
            assert needed in query, f"{needed} not in query"

        assert len(result) == 1
        ts = result[0].tailscaleStatus
        assert isinstance(result[0], DockerContainer)
        assert ts is not None
        assert ts.version == "1.80.0"
        assert ts.latestVersion == "1.82.5"
        assert ts.updateAvailable is True
        assert ts.relay == "sea"
        assert ts.relayName == "Seattle"
        assert ts.tailscaleIps == ["100.64.0.2", "fd7a:115c:a1e0::2"]
        assert ts.primaryRoutes == ["10.0.0.0/24"]
        assert ts.isExitNode is False
        assert ts.exitNodeStatus is not None
        assert ts.exitNodeStatus.online is True
        assert ts.exitNodeStatus.tailscaleIps == ["100.64.0.3"]
        assert ts.keyExpiryDays == 42
        assert ts.keyExpired is False
        assert ts.backendState == "Running"

    async def test_typed_get_containers_populates_labels_network_and_mounts(
        self,
    ) -> None:
        """Extended query must request and parse labels, networkSettings, mounts.

        Home Assistant discovery relies on container labels, and network
        IP/gateway data live under networkSettings. Mounts are needed so
        users can tell at a glance what host paths a container maps.
        """
        from unraid_api.models import DockerContainer

        payload_labels = {
            "net.unraid.docker.webui": "http://[IP]:[PORT:32400]",
            "net.unraid.docker.icon": "plex.png",
        }
        payload_network_settings = {
            "Networks": {
                "bridge": {
                    "IPAddress": "172.17.0.2",
                    "Gateway": "172.17.0.1",
                    "MacAddress": "02:42:ac:11:00:02",
                }
            }
        }
        payload_mounts = [
            {
                "Type": "bind",
                "Source": "/mnt/user/appdata/plex",
                "Destination": "/config",
                "Mode": "rw",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/mnt/user/media",
                "Destination": "/media",
                "Mode": "ro",
                "RW": False,
            },
        ]

        captured_requests: list[str] = []

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            body = kwargs.get("json") or {}
            captured_requests.append(body.get("query", ""))
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "ports": [],
                                    "labels": payload_labels,
                                    "networkSettings": payload_network_settings,
                                    "mounts": payload_mounts,
                                },
                            ]
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers()

        assert len(result) == 1
        assert isinstance(result[0], DockerContainer)

        # Query shape: extended query must actually ask the server for these fields.
        assert captured_requests, "no GraphQL request was captured"
        query = captured_requests[0]
        assert "labels" in query
        assert "networkSettings" in query
        assert "mounts" in query

        # Result shape: parsed model must surface the server data.
        container = result[0]
        assert container.labels == payload_labels
        assert container.networkSettings == payload_network_settings
        assert container.mounts == payload_mounts


class TestTypedGetContainersSafeMethod:
    """Tests for typed_get_containers_safe (lightweight polling variant)."""

    async def test_typed_get_containers_safe(self) -> None:
        """Safe variant returns DockerContainer models with cheap fields."""
        from unraid_api.models import DockerContainer

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "imageId": "sha256:aaa",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                    "autoStartOrder": 1,
                                    "isUpdateAvailable": False,
                                    "iconUrl": "/icons/plex.png",
                                    "webUiUrl": "http://unraid.test:32400",
                                    "projectUrl": "https://plex.tv",
                                    "registryUrl": "https://hub.docker.com",
                                    "supportUrl": "https://forums.plex.tv",
                                    "tailscaleEnabled": False,
                                },
                                {
                                    "id": "container:def456",
                                    "names": ["/sonarr"],
                                    "image": "linuxserver/sonarr",
                                    "imageId": "sha256:bbb",
                                    "state": "stopped",
                                    "status": "Exited (0) 2 hours ago",
                                    "autoStart": False,
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers_safe()

                assert isinstance(result, list)
                assert len(result) == 2
                assert all(isinstance(c, DockerContainer) for c in result)
                assert result[0].id == "container:abc123"
                assert result[0].name == "plex"
                assert result[0].state == "running"
                assert result[0].isUpdateAvailable is False
                assert result[0].iconUrl == "/icons/plex.png"
                assert result[0].webUiUrl == "http://unraid.test:32400"
                assert result[0].tailscaleEnabled is False
                assert result[1].name == "sonarr"
                assert result[1].state == "stopped"

    async def test_typed_get_containers_safe_empty(self) -> None:
        """Safe variant returns empty list when no containers exist."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"docker": {"containers": []}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers_safe()

                assert isinstance(result, list)
                assert len(result) == 0

    async def test_typed_get_containers_safe_expensive_fields_none(self) -> None:
        """Expensive fields stay None because the safe query never asks for them."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_containers_safe()

                container = result[0]
                assert container.sizeRootFs is None
                assert container.sizeRw is None
                assert container.sizeLog is None
                assert container.mounts is None
                assert container.networkSettings is None
                assert container.labels is None
                assert container.tailscaleStatus is None

    async def test_typed_get_containers_safe_query_omits_expensive_fields(
        self,
    ) -> None:
        """The generated query must omit every expensive/heavy field.

        sizeRootFs/sizeRw/sizeLog make the Docker daemon compute writable
        layer sizes (docker ps --size) which causes multi-second CPU spikes
        on every poll (ha-unraid#237).
        """
        captured_requests: list[str] = []

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            body = kwargs.get("json") or {}
            captured_requests.append(body.get("query", ""))
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                },
                            ]
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                await client.typed_get_containers_safe()

        assert captured_requests, "no GraphQL request was captured"
        query = captured_requests[0]

        for needed in (
            "id",
            "names",
            "image",
            "imageId",
            "state",
            "status",
            "autoStart",
            "autoStartOrder",
            "isUpdateAvailable",
            "iconUrl",
            "webUiUrl",
            "projectUrl",
            "registryUrl",
            "supportUrl",
            "tailscaleEnabled",
        ):
            assert re.search(rf"\b{needed}\b", query), f"{needed} not in query"

        for excluded in (
            "sizeRootFs",
            "sizeRw",
            "sizeLog",
            "mounts",
            "networkSettings",
            "labels",
            "ports",
            "templatePorts",
            "hostConfig",
            "tailscaleStatus",
        ):
            assert not re.search(rf"\b{excluded}\b", query), (
                f"expensive field {excluded} must not be in safe query"
            )

    async def test_typed_get_containers_safe_capability_gating(self) -> None:
        """Optional cheap scalars are omitted when the server lacks them."""
        captured_requests: list[str] = []

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            body = kwargs.get("json") or {}
            captured_requests.append(body.get("query", ""))
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "docker": {
                            "containers": [
                                {
                                    "id": "container:abc",
                                    "names": ["/plex"],
                                    "image": "plexinc/pms-docker",
                                    "state": "running",
                                    "status": "Up 5 days",
                                    "autoStart": True,
                                },
                            ]
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                # Old server: only core container fields exist.
                client._capabilities = ServerCapabilities(
                    {
                        "DockerContainer": frozenset(
                            {
                                "id",
                                "names",
                                "image",
                                "imageId",
                                "state",
                                "status",
                                "autoStart",
                                "iconUrl",
                            }
                        )
                    }
                )
                result = await client.typed_get_containers_safe()

        assert len(result) == 1
        assert captured_requests, "no GraphQL request was captured"
        query = captured_requests[0]
        assert "iconUrl" in query
        for missing in (
            "autoStartOrder",
            "isUpdateAvailable",
            "webUiUrl",
            "projectUrl",
            "registryUrl",
            "supportUrl",
            "tailscaleEnabled",
        ):
            assert missing not in query, f"{missing} should be capability-gated out"


class TestTypedGetVmsMethod:
    """Tests for typed_get_vms method (returns list[VmDomain])."""

    async def test_typed_get_vms(self) -> None:
        """Test getting VMs returns list of VmDomain models."""
        from unraid_api.models import VmDomain

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "vms": {
                            "domains": [
                                {
                                    "id": "vm:win10",
                                    "name": "Windows 10",
                                    "state": "RUNNING",
                                },
                                {
                                    "id": "vm:ubuntu",
                                    "name": "Ubuntu Server",
                                    "state": "SHUTOFF",
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_vms()

                assert isinstance(result, list)
                assert len(result) == 2
                assert all(isinstance(vm, VmDomain) for vm in result)
                assert result[0].id == "vm:win10"
                assert result[0].name == "Windows 10"
                assert result[0].state == "RUNNING"
                assert result[1].id == "vm:ubuntu"
                assert result[1].state == "SHUTOFF"

    async def test_typed_get_vms_empty(self) -> None:
        """Test getting VMs returns empty list when none exist."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vms": {"domains": []}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._capabilities = ServerCapabilities.permissive()
                result = await client.typed_get_vms()

                assert isinstance(result, list)
                assert len(result) == 0


class TestTypedGetUpsDevicesMethod:
    """Tests for typed_get_ups_devices method (returns list[UPSDevice])."""

    async def test_typed_get_ups_devices(self) -> None:
        """Test getting UPS devices returns list of UPSDevice models."""
        from unraid_api.models import UPSDevice

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "upsDevices": [
                            {
                                "id": "ups:cyberpower",
                                "name": "CyberPower UPS",
                                "model": "CP1500AVRLCD",
                                "status": "OL",
                                "battery": {
                                    "chargeLevel": 100,
                                    "estimatedRuntime": 3600,
                                },
                                "power": {
                                    "inputVoltage": 120.5,
                                    "outputVoltage": 120.0,
                                    "loadPercentage": 25.0,
                                    "nominalPower": 1500,
                                    "currentPower": 375.0,
                                },
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_ups_devices()

                assert isinstance(result, list)
                assert len(result) == 1
                assert isinstance(result[0], UPSDevice)
                assert result[0].id == "ups:cyberpower"
                assert result[0].name == "CyberPower UPS"
                assert result[0].status == "OL"
                assert result[0].battery.chargeLevel == 100
                assert result[0].power.loadPercentage == 25.0
                assert result[0].power.nominalPower == 1500
                assert result[0].power.currentPower == 375.0

    async def test_typed_get_ups_devices_empty(self) -> None:
        """Test getting UPS devices returns empty list when none exist."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"upsDevices": []}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_ups_devices()

                assert isinstance(result, list)
                assert len(result) == 0


class TestTypedGetArrayMethod:
    """Tests for typed_get_array method (returns UnraidArray model)."""

    async def test_typed_get_array(self) -> None:
        """Test getting array returns UnraidArray model."""
        from unraid_api.models import UnraidArray

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "state": "STARTED",
                            "capacity": {
                                "kilobytes": {
                                    "total": 10000000000,
                                    "used": 4000000000,
                                    "free": 6000000000,
                                }
                            },
                            "parityCheckStatus": {
                                "status": "IDLE",
                                "progress": 0,
                                "running": False,
                                "errors": 0,
                            },
                            "boot": {
                                "id": "disk:boot",
                                "name": "flash",
                                "device": "sdc",
                                "size": 32000000,
                            },
                            "parities": [
                                {
                                    "id": "disk:parity1",
                                    "idx": 0,
                                    "name": "Parity",
                                    "device": "sda",
                                    "size": 4000000000,
                                    "status": "DISK_OK",
                                    "temp": 35,
                                    "isSpinning": True,
                                }
                            ],
                            "disks": [
                                {
                                    "id": "disk:disk1",
                                    "idx": 1,
                                    "name": "Disk 1",
                                    "device": "sdb",
                                    "size": 4000000000,
                                    "status": "DISK_OK",
                                    "temp": 38,
                                    "isSpinning": True,
                                    "fsSize": 3900000000,
                                    "fsUsed": 2000000000,
                                    "fsFree": 1900000000,
                                }
                            ],
                            "caches": [],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_array()

                assert isinstance(result, UnraidArray)
                assert result.state == "STARTED"
                assert result.capacity.kilobytes.total == 10000000000
                assert len(result.parities) == 1
                assert result.parities[0].id == "disk:parity1"
                assert result.parities[0].temp == 35
                assert len(result.disks) == 1
                assert result.disks[0].name == "Disk 1"
                assert result.boot is not None
                assert result.boot.name == "flash"


class TestTypedGetSharesMethod:
    """Tests for typed_get_shares method (returns list[Share])."""

    async def test_typed_get_shares(self) -> None:
        """Test getting shares returns list of Share models."""
        from unraid_api.models import Share

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "shares": [
                            {
                                "id": "share:appdata",
                                "name": "appdata",
                                "size": 0,
                                "used": 50000000,
                                "free": 100000000,
                            },
                            {
                                "id": "share:media",
                                "name": "media",
                                "size": 500000000,
                                "used": 300000000,
                                "free": 200000000,
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_shares()

                assert isinstance(result, list)
                assert len(result) == 2
                assert all(isinstance(s, Share) for s in result)
                assert result[0].id == "share:appdata"
                assert result[0].name == "appdata"
                assert result[1].id == "share:media"
                assert result[1].size == 500000000

    async def test_typed_get_shares_empty(self) -> None:
        """Test getting shares returns empty list when none exist."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"shares": []}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_shares()

                assert isinstance(result, list)
                assert len(result) == 0


class TestGetNotificationOverviewMethod:
    """Tests for get_notification_overview method (returns NotificationOverview)."""

    async def test_get_notification_overview(self) -> None:
        """Test getting notification overview returns NotificationOverview model."""
        from unraid_api.models import NotificationOverview

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "notifications": {
                            "overview": {
                                "unread": {
                                    "info": 3,
                                    "warning": 1,
                                    "alert": 0,
                                    "total": 4,
                                },
                                "archive": {
                                    "info": 50,
                                    "warning": 10,
                                    "alert": 2,
                                    "total": 62,
                                },
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_notification_overview()

                assert isinstance(result, NotificationOverview)
                assert result.unread.info == 3
                assert result.unread.warning == 1
                assert result.unread.alert == 0
                assert result.unread.total == 4
                assert result.archive.total == 62

    async def test_get_notification_overview_empty(self) -> None:
        """Test notification overview with no notifications."""
        from unraid_api.models import NotificationOverview

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "notifications": {
                            "overview": {
                                "unread": {
                                    "info": 0,
                                    "warning": 0,
                                    "alert": 0,
                                    "total": 0,
                                },
                                "archive": {
                                    "info": 0,
                                    "warning": 0,
                                    "alert": 0,
                                    "total": 0,
                                },
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_notification_overview()

                assert isinstance(result, NotificationOverview)
                assert result.unread.total == 0
                assert result.archive.total == 0


class TestGetRegistrationMethod:
    """Tests for get_registration and typed_get_registration methods."""

    async def test_get_registration(self) -> None:
        """Test getting registration information."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "registration": {
                            "id": "registration:1",
                            "type": "Pro",
                            "state": "VALID",
                            "expiration": "2025-12-31",
                            "updateExpiration": "2025-12-31",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_registration()

                assert result["id"] == "registration:1"
                assert result["type"] == "Pro"
                assert result["state"] == "VALID"

    async def test_typed_get_registration(self) -> None:
        """Test getting registration as Pydantic model."""
        from unraid_api.models import Registration

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "registration": {
                            "id": "registration:1",
                            "type": "Pro",
                            "state": "VALID",
                            "expiration": None,
                            "updateExpiration": None,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_registration()

                assert isinstance(result, Registration)
                assert result.id == "registration:1"
                assert result.type == "Pro"
                assert result.state == "VALID"


class TestGetVarsMethod:
    """Tests for get_vars method."""

    async def test_get_vars(self) -> None:
        """Test getting system variables."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "vars": {
                            "id": "vars:1",
                            "version": "7.2.3",
                            "name": "Cube",
                            "timeZone": "UTC",
                            "mdNumDisks": 4,
                            "mdState": "STARTED",
                            "fsState": "Running",
                            "shareCount": 10,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_vars()

                assert result["id"] == "vars:1"
                assert result["version"] == "7.2.3"
                assert result["name"] == "Cube"
                assert result["timeZone"] == "UTC"
                assert result["mdNumDisks"] == 4

    async def test_typed_get_vars(self) -> None:
        """Test getting system variables as Pydantic model."""
        from unraid_api.models import Vars

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "vars": {
                            "id": "vars:1",
                            "version": "7.2.3",
                            "name": "Cube",
                            "timeZone": "America/New_York",
                            "mdState": "STARTED",
                            "shareCount": 15,
                            "shareSmbEnabled": True,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_vars()

                assert isinstance(result, Vars)
                assert result.name == "Cube"
                assert result.time_zone == "America/New_York"
                assert result.md_state == "STARTED"
                assert result.share_count == 15
                assert result.share_smb_enabled is True


class TestGetServicesMethod:
    """Tests for get_services and typed_get_services methods."""

    async def test_get_services(self) -> None:
        """Test getting services list."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "services": [
                            {
                                "id": "service:sshd",
                                "name": "sshd",
                                "online": True,
                                "uptime": {"timestamp": "2024-01-15T10:30:00Z"},
                                "version": "9.6",
                            },
                            {
                                "id": "service:docker",
                                "name": "docker",
                                "online": True,
                                "uptime": {"timestamp": "2024-01-15T10:30:00Z"},
                                "version": "24.0.7",
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_services()

                assert len(result) == 2
                assert result[0]["name"] == "sshd"
                assert result[0]["online"] is True

    async def test_typed_get_services(self) -> None:
        """Test getting services as Pydantic models."""
        from unraid_api.models import Service

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "services": [
                            {
                                "id": "service:sshd",
                                "name": "sshd",
                                "online": True,
                                "uptime": {"timestamp": "2024-01-15T10:30:00Z"},
                                "version": "9.6",
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_services()

                assert len(result) == 1
                assert isinstance(result[0], Service)
                assert result[0].name == "sshd"
                assert result[0].online is True


class TestGetFlashMethod:
    """Tests for get_flash and typed_get_flash methods."""

    async def test_get_flash(self) -> None:
        """Test getting flash drive information."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "flash": {
                            "id": "flash:1",
                            "product": "Ultra Fit",
                            "vendor": "SanDisk",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_flash()

                assert result["vendor"] == "SanDisk"

    async def test_typed_get_flash(self) -> None:
        """Test getting flash drive as Pydantic model."""
        from unraid_api.models import Flash

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "flash": {
                            "id": "flash:1",
                            "product": "Ultra Fit",
                            "vendor": "SanDisk",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_flash()

                assert isinstance(result, Flash)
                assert result.vendor == "SanDisk"


class TestGetOwnerMethod:
    """Tests for get_owner and typed_get_owner methods."""

    async def test_get_owner(self) -> None:
        """Test getting owner information."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "owner": {
                            "username": "admin",
                            "avatar": "https://example.com/avatar.png",
                            "url": "https://my.unraid.net",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_owner()

                assert result["username"] == "admin"

    async def test_typed_get_owner(self) -> None:
        """Test getting owner as Pydantic model."""
        from unraid_api.models import Owner

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "owner": {
                            "username": "admin",
                            "avatar": None,
                            "url": None,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_owner()

                assert isinstance(result, Owner)
                assert result.username == "admin"


class TestGetPluginsMethod:
    """Tests for get_plugins and typed_get_plugins methods."""

    async def test_get_plugins(self) -> None:
        """Test getting installed plugins."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "plugins": [
                            {
                                "name": "Dynamix System Stats",
                                "version": "2024.01.01",
                                "hasApiModule": True,
                                "hasCliModule": False,
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_plugins()

                assert len(result) == 1
                assert result[0]["name"] == "Dynamix System Stats"

    async def test_typed_get_plugins(self) -> None:
        """Test getting plugins as Pydantic models."""
        from unraid_api.models import Plugin

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "plugins": [
                            {
                                "name": "Test Plugin",
                                "version": "1.0",
                                "hasApiModule": True,
                                "hasCliModule": None,
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_plugins()

                assert len(result) == 1
                assert isinstance(result[0], Plugin)
                assert result[0].hasApiModule is True


class TestGetDockerNetworksMethod:
    """Tests for get_docker_networks and typed_get_docker_networks methods."""

    async def test_get_docker_networks(self) -> None:
        """Test getting Docker networks."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "networks": [
                                {
                                    "id": "network:bridge",
                                    "name": "bridge",
                                    "created": "2024-01-01T00:00:00Z",
                                    "scope": "local",
                                    "driver": "bridge",
                                    "enableIPv6": False,
                                    "internal": False,
                                    "attachable": False,
                                    "ingress": False,
                                    "configOnly": False,
                                }
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_docker_networks()

                assert len(result) == 1
                assert result[0]["name"] == "bridge"

    async def test_typed_get_docker_networks(self) -> None:
        """Test getting Docker networks as Pydantic models."""
        from unraid_api.models import DockerNetwork

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "networks": [
                                {
                                    "id": "network:br0",
                                    "name": "br0",
                                    "created": None,
                                    "scope": "local",
                                    "driver": "macvlan",
                                    "enableIPv6": False,
                                    "internal": False,
                                    "attachable": False,
                                    "ingress": False,
                                    "configOnly": False,
                                }
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_docker_networks()

                assert len(result) == 1
                assert isinstance(result[0], DockerNetwork)
                assert result[0].driver == "macvlan"


class TestGetLogFilesMethod:
    """Tests for get_log_files and typed_get_log_files methods."""

    async def test_get_log_files(self) -> None:
        """Test getting log files list."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "logFiles": [
                            {
                                "id": "log:syslog",
                                "name": "syslog",
                                "path": "/var/log/syslog",
                            },
                            {
                                "id": "log:docker",
                                "name": "docker",
                                "path": "/var/log/docker.log",
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_log_files()

                assert len(result) == 2
                assert result[0]["name"] == "syslog"

    async def test_typed_get_log_files(self) -> None:
        """Test getting log files as Pydantic models."""
        from unraid_api.models import LogFile

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "logFiles": [
                            {
                                "id": "log:syslog",
                                "name": "syslog",
                                "path": "/var/log/syslog",
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_log_files()

                assert len(result) == 1
                assert isinstance(result[0], LogFile)
                assert result[0].path == "/var/log/syslog"

    async def test_get_log_file(self) -> None:
        """Test getting log file contents."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "logFile": {"log": "Jan 1 00:00:00 server test: Log entry\n"}
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_log_file("log:syslog")

                assert "log" in result
                assert "Log entry" in result["log"]

    async def test_get_log_file_with_lines(self) -> None:
        """Test getting log file contents with lines parameter."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "logFile": {
                            "path": "/var/log/syslog",
                            "content": "Line 1\nLine 2\n",
                            "totalLines": 100,
                            "startLine": 90,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_log_file("log:syslog", lines=10)

                assert "content" in result
                assert result["totalLines"] == 100


class TestGetArrayDisksMethod:
    """Tests for get_array_disks method."""

    async def test_get_array_disks(self) -> None:
        """Test getting array disk info without waking disks."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "boot": {
                                "id": "boot:0",
                                "name": "Flash",
                                "device": "sda",
                                "size": 16000000000,
                                "status": "DISK_OK",
                                "type": "Flash",
                                "temp": None,
                                "fsSize": 15000000000,
                                "fsUsed": 5000000000,
                                "fsFree": 10000000000,
                                "fsType": "vfat",
                            },
                            "disks": [
                                {
                                    "id": "disk:1",
                                    "idx": 1,
                                    "name": "Disk 1",
                                    "device": "sdb",
                                    "size": 4000000000000,
                                    "status": "DISK_OK",
                                    "type": "Data",
                                    "temp": 35,
                                    "fsSize": 3900000000000,
                                    "fsUsed": 2000000000000,
                                    "fsFree": 1900000000000,
                                    "fsType": "xfs",
                                    "isSpinning": True,
                                }
                            ],
                            "parities": [
                                {
                                    "id": "parity:0",
                                    "idx": 0,
                                    "name": "Parity",
                                    "device": "sdc",
                                    "size": 4000000000000,
                                    "status": "DISK_OK",
                                    "type": "Parity",
                                    "temp": 33,
                                    "isSpinning": True,
                                }
                            ],
                            "caches": [
                                {
                                    "id": "cache:0",
                                    "idx": 0,
                                    "name": "Cache",
                                    "device": "nvme0n1",
                                    "size": 500000000000,
                                    "status": "DISK_OK",
                                    "type": "Cache",
                                    "temp": 40,
                                    "fsSize": 480000000000,
                                    "fsUsed": 100000000000,
                                    "fsFree": 380000000000,
                                    "fsType": "btrfs",
                                    "isSpinning": False,
                                }
                            ],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_array_disks()

                assert result["boot"]["id"] == "boot:0"
                assert len(result["disks"]) == 1
                assert result["disks"][0]["isSpinning"] is True
                assert len(result["parities"]) == 1
                assert len(result["caches"]) == 1


class TestGetCloudMethod:
    """Tests for get_cloud and typed_get_cloud (deprecated) methods."""

    async def test_get_cloud(self) -> None:
        """Test getting cloud settings emits deprecation warning."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "cloud": {
                            "error": None,
                            "apiKey": {"valid": True, "error": None},
                            "relay": {"status": "connected", "timeout": "5000"},
                            "minigraphql": {"status": "CONNECTED", "timeout": 30},
                            "cloud": {"status": "ok", "ip": "unraid.test"},
                            "allowedOrigins": ["http://localhost"],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.warns(DeprecationWarning, match="get_cloud"):
                    result = await client.get_cloud()

                assert result["cloud"]["status"] == "ok"

    async def test_typed_get_cloud(self) -> None:
        """Test getting cloud settings as Pydantic model emits deprecation."""
        from unraid_api.models import Cloud

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "cloud": {
                            "error": None,
                            "apiKey": {"valid": True, "error": None},
                            "relay": None,
                            "minigraphql": {"status": "CONNECTED"},
                            "cloud": {"status": "ok", "ip": None},
                            "allowedOrigins": [],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.warns(DeprecationWarning, match="get_cloud"):
                    result = await client.typed_get_cloud()

                assert isinstance(result, Cloud)
                assert result.cloud is not None
                assert result.cloud.status == "ok"


class TestGetConnectMethod:
    """Tests for get_connect and typed_get_connect (deprecated) methods."""

    async def test_get_connect(self) -> None:
        """Test getting Connect information emits deprecation warning."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "connect": {
                            "id": "connect:1",
                            "dynamicRemoteAccess": {
                                "enabledType": "UPNP",
                                "runningType": "UPNP",
                                "error": None,
                            },
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.warns(DeprecationWarning, match="get_connect"):
                    result = await client.get_connect()

                assert result["dynamicRemoteAccess"]["enabledType"] == "UPNP"

    async def test_typed_get_connect(self) -> None:
        """Test getting Connect as Pydantic model emits deprecation."""
        from unraid_api.models import Connect

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "connect": {
                            "id": "connect:1",
                            "dynamicRemoteAccess": {
                                "enabledType": "DISABLED",
                                "runningType": "DISABLED",
                                "error": None,
                            },
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.warns(DeprecationWarning, match="get_connect"):
                    result = await client.typed_get_connect()

                assert isinstance(result, Connect)
                assert result.dynamicRemoteAccess is not None
                assert result.dynamicRemoteAccess.enabledType == "DISABLED"


class TestGetRemoteAccessMethod:
    """Tests for get_remote_access and typed (deprecated) methods."""

    async def test_get_remote_access(self) -> None:
        """Test getting remote access emits deprecation warning."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "remoteAccess": {
                            "accessType": "ALWAYS",
                            "forwardType": "UPNP",
                            "port": 443,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.warns(DeprecationWarning, match="get_remote_access"):
                    result = await client.get_remote_access()

                assert result["accessType"] == "ALWAYS"
                assert result["port"] == 443

    async def test_typed_get_remote_access(self) -> None:
        """Test getting remote access model emits deprecation."""
        from unraid_api.models import RemoteAccess

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "remoteAccess": {
                            "accessType": "DISABLED",
                            "forwardType": None,
                            "port": None,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.warns(
                    DeprecationWarning,
                    match="get_remote_access",
                ):
                    result = await client.typed_get_remote_access()

                assert isinstance(result, RemoteAccess)
                assert result.accessType == "DISABLED"


class TestNotificationMutations:
    """Tests for notification mutation methods.

    All notification mutations are root-level (not nested under 'notifications').
    See: https://github.com/ruaan-deysel/unraid-api/issues/24
    """

    async def test_archive_notification(self) -> None:
        """Test archiving a notification uses root-level archiveNotification."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "archiveNotification": {
                            "id": "notification:123",
                            "title": "Test",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.archive_notification("notification:123")

                assert "archiveNotification" in result
                assert result["archiveNotification"]["id"] == "notification:123"

    async def test_unarchive_notification(self) -> None:
        """Test unarchiving a notification uses root-level unreadNotification."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "unreadNotification": {
                            "id": "notification:123",
                            "title": "Test",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.unarchive_notification("notification:123")

                assert "unreadNotification" in result
                assert result["unreadNotification"]["id"] == "notification:123"

    async def test_delete_notification(self) -> None:
        """Test deleting a notification uses root-level deleteNotification with type."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "deleteNotification": {
                            "unread": {"total": 5},
                            "archive": {"total": 0},
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.delete_notification(
                    "notification:123", notification_type="ARCHIVE"
                )

                assert "deleteNotification" in result
                assert result["deleteNotification"]["unread"]["total"] == 5

    async def test_delete_notification_default_type(self) -> None:
        """Test delete_notification defaults to ARCHIVE type."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "deleteNotification": {
                            "unread": {"total": 3},
                            "archive": {"total": 0},
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.delete_notification("notification:123")

                assert "deleteNotification" in result

    async def test_archive_all_notifications(self) -> None:
        """Test archiving all notifications uses root-level archiveAll."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "archiveAll": {
                            "unread": {"total": 0},
                            "archive": {"total": 10},
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.archive_all_notifications()

                assert "archiveAll" in result
                assert result["archiveAll"]["unread"]["total"] == 0

    async def test_delete_all_notifications(self) -> None:
        """Test deleting all archived uses root-level deleteArchivedNotifications."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "deleteArchivedNotifications": {
                            "unread": {"total": 5},
                            "archive": {"total": 0},
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.delete_all_notifications()

                assert "deleteArchivedNotifications" in result
                assert result["deleteArchivedNotifications"]["archive"]["total"] == 0


class TestResetVmMethod:
    """Tests for reset_vm method."""

    async def test_reset_vm(self) -> None:
        """Test resetting a virtual machine."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"vm": {"reset": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.reset_vm("vm:test-vm")

                assert result["vm"]["reset"] is True


class TestArrayDiskManagementMethods:
    """Tests for array disk management methods."""

    async def test_add_array_disk(self) -> None:
        """Test adding a disk to the array."""
        disk = {"id": "disk:sdb", "name": "disk1", "status": "DISK_OK"}
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "addDiskToArray": {
                                "state": "STARTED",
                                "disks": [disk],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.add_array_disk("disk:sdb")

                assert result["array"]["addDiskToArray"]["state"] == "STARTED"

    async def test_add_array_disk_with_slot(self) -> None:
        """Test adding a disk to the array with a slot parameter."""
        disk = {"id": "disk:sdb", "name": "disk1", "status": "DISK_OK"}
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "addDiskToArray": {
                                "state": "STARTED",
                                "disks": [disk],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.add_array_disk("disk:sdb", slot=3)

                assert result["array"]["addDiskToArray"]["state"] == "STARTED"

    async def test_remove_array_disk(self) -> None:
        """Test removing a disk from the array."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "removeDiskFromArray": {
                                "state": "STOPPED",
                                "disks": [],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._capabilities = ServerCapabilities.permissive()
                with pytest.warns(DeprecationWarning):
                    result = await client.remove_array_disk("disk:sdb")

                assert "removeDiskFromArray" in result["array"]

    async def test_remove_array_disk_with_slot(self) -> None:
        """Test removing a disk from the array with a slot parameter."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "removeDiskFromArray": {
                                "state": "STOPPED",
                                "disks": [],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._capabilities = ServerCapabilities.permissive()
                with pytest.warns(DeprecationWarning):
                    result = await client.remove_array_disk("disk:sdb", slot=5)

                assert "removeDiskFromArray" in result["array"]

    async def test_clear_disk_stats(self) -> None:
        """Test clearing disk statistics."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"array": {"clearArrayDiskStatistics": True}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.clear_disk_stats("disk:sdb")

                assert result["array"]["clearArrayDiskStatistics"] is True


class TestRestartContainerMethod:
    """Tests for restart_container convenience method."""

    async def test_restart_container(self) -> None:
        """Test restart_container calls stop then start."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            # Stop response
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "stop": {
                                "id": "container:plex",
                                "state": "EXITED",
                                "status": "Exited (0)",
                            }
                        }
                    }
                },
            )
            # Start response
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "start": {
                                "id": "container:plex",
                                "state": "RUNNING",
                                "status": "Up 1 second",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._capabilities = ServerCapabilities({})
                result = await client.restart_container("container:plex", delay=0.0)

                assert result["docker"]["start"]["state"] == "RUNNING"

    async def test_restart_container_default_delay(self) -> None:
        """Test that restart_container has a default delay parameter."""
        import inspect

        sig = inspect.signature(UnraidClient.restart_container)
        assert sig.parameters["delay"].default == 1.0


class TestContainerLogMethods:
    """Tests for container log retrieval methods."""

    async def test_get_container_logs(self) -> None:
        """Test getting raw container logs."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "logs": {
                                "containerId": "container:abc123",
                                "lines": [
                                    {
                                        "timestamp": "2026-01-15T10:30:00Z",
                                        "message": "Starting...",
                                    },
                                    {
                                        "timestamp": "2026-01-15T10:30:01Z",
                                        "message": "Ready.",
                                    },
                                ],
                                "cursor": "2026-01-15T10:30:01Z",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_container_logs("container:abc123", tail=10)

                assert result["containerId"] == "container:abc123"
                assert len(result["lines"]) == 2
                assert result["lines"][0]["message"] == "Starting..."

    async def test_get_container_logs_with_since(self) -> None:
        """Test getting container logs with since parameter."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "logs": {
                                "containerId": "container:abc123",
                                "lines": [],
                                "cursor": None,
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_container_logs(
                    "container:abc123", since="2026-01-15T10:30:00Z"
                )

                assert result["containerId"] == "container:abc123"
                assert result["lines"] == []

    async def test_typed_get_container_logs(self) -> None:
        """Test getting typed container logs."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "logs": {
                                "containerId": "container:abc123",
                                "lines": [
                                    {
                                        "timestamp": "2026-01-15T10:30:00Z",
                                        "message": "Hello world",
                                    }
                                ],
                                "cursor": "2026-01-15T10:30:00Z",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                logs = await client.typed_get_container_logs("container:abc123", tail=5)

                assert logs.containerId == "container:abc123"
                assert len(logs.lines) == 1
                assert logs.lines[0].message == "Hello world"
                assert logs.cursor == "2026-01-15T10:30:00Z"


class TestUserAccountMethods:
    """Tests for user account methods."""

    async def test_get_me(self) -> None:
        """Test getting current user info."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "me": {
                            "id": "user:abc123",
                            "name": "admin",
                            "description": "Admin API key",
                            "roles": ["ADMIN"],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_me()

                assert result["id"] == "user:abc123"
                assert result["name"] == "admin"
                assert result["roles"] == ["ADMIN"]

    async def test_typed_get_me(self) -> None:
        """Test getting current user as typed model."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "me": {
                            "id": "user:abc123",
                            "name": "viewer",
                            "description": "Viewer key",
                            "roles": ["VIEWER"],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                user = await client.typed_get_me()

                assert user.id == "user:abc123"
                assert user.name == "viewer"
                assert user.roles == ["VIEWER"]


class TestApiKeyManagementMethods:
    """Tests for API key management methods."""

    async def test_get_api_keys(self) -> None:
        """Test listing all API keys."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKeys": [
                            {
                                "id": "apikey:111",
                                "name": "Connect",
                                "description": "Connect key",
                                "roles": ["CONNECT"],
                                "createdAt": "2026-01-01T00:00:00Z",
                            },
                            {
                                "id": "apikey:222",
                                "name": "Admin Key",
                                "description": None,
                                "roles": ["ADMIN"],
                                "createdAt": "2026-01-02T00:00:00Z",
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_api_keys()

                assert len(result) == 2
                assert result[0]["name"] == "Connect"
                assert result[1]["roles"] == ["ADMIN"]

    async def test_typed_get_api_keys(self) -> None:
        """Test listing API keys as typed models."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKeys": [
                            {
                                "id": "apikey:111",
                                "name": "My Key",
                                "description": "Test",
                                "roles": ["ADMIN"],
                                "createdAt": "2026-01-01T00:00:00Z",
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                keys = await client.typed_get_api_keys()

                assert len(keys) == 1
                assert keys[0].id == "apikey:111"
                assert keys[0].name == "My Key"
                assert keys[0].roles == ["ADMIN"]

    async def test_create_api_key(self) -> None:
        """Test creating a new API key."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKey": {
                            "create": {
                                "id": "apikey:new",
                                "key": "generated-secret-key-value",
                                "name": "New Key",
                                "description": "For my app",
                                "roles": ["VIEWER"],
                                "createdAt": "2026-02-07T00:00:00Z",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.create_api_key(
                    "New Key",
                    description="For my app",
                    roles=["VIEWER"],
                )

                assert result["id"] == "apikey:new"
                assert result["key"] == "generated-secret-key-value"
                assert result["name"] == "New Key"

    async def test_create_api_key_minimal(self) -> None:
        """Test creating an API key with only required fields."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKey": {
                            "create": {
                                "id": "apikey:min",
                                "key": "min-key-value",
                                "name": "Minimal",
                                "description": None,
                                "roles": [],
                                "createdAt": "2026-02-07T00:00:00Z",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.create_api_key("Minimal")

                assert result["name"] == "Minimal"

    async def test_update_api_key(self) -> None:
        """Test updating an API key."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKey": {
                            "update": {
                                "id": "apikey:123",
                                "name": "Renamed Key",
                                "description": "Updated desc",
                                "roles": ["ADMIN"],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.update_api_key(
                    "apikey:123",
                    name="Renamed Key",
                    description="Updated desc",
                )

                assert result["id"] == "apikey:123"
                assert result["name"] == "Renamed Key"

    async def test_update_api_key_no_optional_params(self) -> None:
        """Test updating an API key with no optional params (id only)."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKey": {
                            "update": {
                                "id": "apikey:123",
                                "name": "Unchanged",
                                "description": None,
                                "roles": ["ADMIN"],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.update_api_key("apikey:123")

                assert result["id"] == "apikey:123"

    async def test_delete_api_keys(self) -> None:
        """Test deleting API keys."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "apiKey": {
                            "delete": True,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.delete_api_keys(["apikey:123", "apikey:456"])

                assert result["apiKey"]["delete"] is True


class TestCloseExceptionHandling:
    """Tests for exception handling in close()."""

    async def test_close_suppresses_exceptions(self) -> None:
        """Test that close() suppresses exceptions from session.close()."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.close = AsyncMock(side_effect=Exception("cleanup error"))

        client = UnraidClient("unraid.test", "test-key")
        client._session = mock_session
        client._owns_session = True

        # Should not raise
        await client.close()
        assert client._session is None


class TestMakeRequestExceptionWrapping:
    """Tests for exception wrapping in _make_request."""

    async def test_client_response_error_401_wrapped(self) -> None:
        """Test that ClientResponseError 401 becomes UnraidAuthenticationError.

        Patches the session directly: aiointercept can only raise
        ClientConnectionError, but this test needs a raised
        ClientResponseError to exercise the wrapping path.
        """
        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            client._resolved_url = "http://unraid.test/graphql"
            assert client._session is not None
            with (
                patch.object(
                    client._session,
                    "post",
                    side_effect=aiohttp.ClientResponseError(
                        request_info=MagicMock(),
                        history=(),
                        status=401,
                        message="Unauthorized",
                    ),
                ),
                pytest.raises(UnraidAuthenticationError),
            ):
                await client.query("query { online }")

    async def test_client_response_error_500_wrapped(self) -> None:
        """Test that ClientResponseError 500 becomes UnraidAPIError."""
        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            client._resolved_url = "http://unraid.test/graphql"
            assert client._session is not None
            with (
                patch.object(
                    client._session,
                    "post",
                    side_effect=aiohttp.ClientResponseError(
                        request_info=MagicMock(),
                        history=(),
                        status=500,
                        message="Internal Server Error",
                    ),
                ),
                pytest.raises(UnraidAPIError, match="HTTP error 500"),
            ):
                await client.query("query { online }")


class TestDiscoverTimeoutCustomPort:
    """Tests for timeout during discovery with custom port."""

    async def test_timeout_custom_port_raises(self) -> None:
        """Test that timeout on custom port raises UnraidTimeoutError."""
        async with UnraidClient(
            "unraid.test",
            "test-key",
            http_port=880,
            verify_ssl=False,
        ) as client:
            assert client._session is not None
            with (
                patch.object(
                    client._session,
                    "get",
                    side_effect=TimeoutError("Connection timed out"),
                ),
                pytest.raises(UnraidTimeoutError, match="port 880"),
            ):
                await client._discover_redirect_url()


class TestCheckCompatibility:
    """Tests for version compatibility checking."""

    async def test_compatible_versions(self) -> None:
        """Test check_compatibility with compatible versions."""

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "versions": {"core": {"unraid": "7.2.4", "api": "4.31.1"}}
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.check_compatibility()
                assert result.unraid == "7.2.4"
                assert result.api == "4.31.1"

    async def test_incompatible_api_version(self) -> None:
        """Test check_compatibility raises for old API version."""
        from unraid_api.exceptions import UnraidVersionError

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "versions": {"core": {"unraid": "7.2.3", "api": "3.0.0"}}
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidVersionError, match="API version"):
                    await client.check_compatibility()

    async def test_incompatible_unraid_version(self) -> None:
        """Test check_compatibility raises for old Unraid version."""
        from unraid_api.exceptions import UnraidVersionError

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "versions": {"core": {"unraid": "6.0.0", "api": "4.31.1"}}
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(UnraidVersionError, match="Unraid version"):
                    await client.check_compatibility()

    async def test_unknown_version_no_raise(self) -> None:
        """Test check_compatibility doesn't raise for unparseable versions."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "versions": {
                                "core": {"unraid": "unknown", "api": "unknown"}
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                # Should not raise - just warns about unparseable versions
                result = await client.check_compatibility()
                assert result.unraid == "unknown"


class TestGetContainerUpdateStatusesMethod:
    """Tests for get_container_update_statuses method."""

    async def test_get_container_update_statuses(self) -> None:
        """Test getting container update statuses returns list of models."""
        from unraid_api.models import ContainerUpdateStatus

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "containerUpdateStatuses": [
                                {
                                    "name": "plex",
                                    "updateStatus": "UP_TO_DATE",
                                },
                                {
                                    "name": "sonarr",
                                    "updateStatus": "UPDATE_AVAILABLE",
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_container_update_statuses()

                assert len(result) == 2
                assert all(isinstance(s, ContainerUpdateStatus) for s in result)
                assert result[0].name == "plex"
                assert result[0].updateStatus == "UP_TO_DATE"
                assert result[1].name == "sonarr"
                assert result[1].updateStatus == "UPDATE_AVAILABLE"

    async def test_get_container_update_statuses_empty(self) -> None:
        """Test getting container update statuses with no containers."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"docker": {"containerUpdateStatuses": []}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_container_update_statuses()
                assert result == []


class TestGetUpsConfigurationMethod:
    """Tests for get_ups_configuration method."""

    async def test_get_ups_configuration(self) -> None:
        """Test getting UPS configuration returns model."""
        from unraid_api.models import UPSConfiguration

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "upsConfiguration": {
                            "service": "apcupsd",
                            "upsCable": "usb",
                            "customUpsCable": None,
                            "upsType": "usb",
                            "device": "/dev/usb/hiddev0",
                            "overrideUpsCapacity": False,
                            "batteryLevel": 10,
                            "minutes": 5,
                            "timeout": 0,
                            "killUps": False,
                            "nisIp": "0.0.0.0",
                            "netServer": "off",
                            "upsName": "APC Back-UPS",
                            "modelName": "Back-UPS 650",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_ups_configuration()

                assert isinstance(result, UPSConfiguration)
                assert result.service == "apcupsd"
                assert result.upsCable == "usb"
                assert result.device == "/dev/usb/hiddev0"
                assert result.batteryLevel == 10
                assert result.minutes == 5
                assert result.killUps is False
                assert result.modelName == "Back-UPS 650"

    async def test_get_ups_configuration_empty(self) -> None:
        """Test getting UPS configuration when no UPS configured."""
        from unraid_api.models import UPSConfiguration

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"upsConfiguration": {}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_ups_configuration()

                assert isinstance(result, UPSConfiguration)
                assert result.service is None
                assert result.upsCable is None


class TestGetDisplaySettingsMethod:
    """Tests for get_display_settings method."""

    async def test_get_display_settings(self) -> None:
        """Test getting display settings returns model with temp thresholds."""
        from unraid_api.models import DisplaySettings

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "display": {
                                "theme": "white",
                                "unit": "CELSIUS",
                                "scale": False,
                                "tabs": False,
                                "resize": True,
                                "wwn": False,
                                "total": True,
                                "usage": True,
                                "text": False,
                                "warning": 55,
                                "critical": 65,
                                "hot": 45,
                                "max": 70,
                                "locale": "en_US",
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_display_settings()

                assert isinstance(result, DisplaySettings)
                assert result.theme == "white"
                assert result.unit == "CELSIUS"
                assert result.warning == 55
                assert result.critical == 65
                assert result.hot == 45
                assert result.max == 70
                assert result.locale == "en_US"

    async def test_get_display_settings_empty(self) -> None:
        """Test getting display settings with empty response."""
        from unraid_api.models import DisplaySettings

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"info": {"display": {}}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_display_settings()

                assert isinstance(result, DisplaySettings)
                assert result.unit is None
                assert result.warning is None
                assert result.critical is None


class TestGetDockerPortConflictsMethod:
    """Tests for get_docker_port_conflicts method."""

    async def test_get_docker_port_conflicts(self) -> None:
        """Test getting Docker port conflicts returns model."""
        from unraid_api.models import DockerPortConflicts

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "portConflicts": {
                                "lanPorts": [
                                    {
                                        "containers": [
                                            {"name": "plex"},
                                            {"name": "jellyfin"},
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_docker_port_conflicts()

                assert isinstance(result, DockerPortConflicts)
                assert len(result.lanPorts) == 1
                assert len(result.lanPorts[0].containers) == 2
                assert result.lanPorts[0].containers[0].name == "plex"
                assert result.lanPorts[0].containers[1].name == "jellyfin"

    async def test_get_docker_port_conflicts_none(self) -> None:
        """Test getting Docker port conflicts with no conflicts."""
        from unraid_api.models import DockerPortConflicts

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"docker": {"portConflicts": {"lanPorts": []}}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_docker_port_conflicts()

                assert isinstance(result, DockerPortConflicts)
                assert result.lanPorts == []


class TestGetTemperatureMetricsMethod:
    """Tests for get_temperature_metrics method."""

    async def test_get_temperature_metrics(self) -> None:
        """Test getting temperature metrics returns TemperatureMetrics."""
        from unraid_api.models import TemperatureMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "temperature": {
                                "id": "temp:1",
                                "summary": {
                                    "average": 35.0,
                                    "hottest": {
                                        "name": "CPU",
                                        "current": {
                                            "value": 55.0,
                                            "unit": "CELSIUS",
                                        },
                                    },
                                    "coolest": {
                                        "name": "SSD",
                                        "current": {
                                            "value": 25.0,
                                            "unit": "CELSIUS",
                                        },
                                    },
                                    "warningCount": 0,
                                    "criticalCount": 0,
                                },
                                "sensors": [
                                    {
                                        "id": "disk:1",
                                        "name": "ST8000VN004",
                                        "type": "DISK",
                                        "location": None,
                                        "current": {
                                            "value": 30.0,
                                            "unit": "CELSIUS",
                                            "status": "NORMAL",
                                        },
                                        "min": {
                                            "value": 28.0,
                                            "unit": "CELSIUS",
                                        },
                                        "max": {
                                            "value": 35.0,
                                            "unit": "CELSIUS",
                                        },
                                        "warning": 50,
                                        "critical": 60,
                                    }
                                ],
                            }
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_temperature_metrics()

                assert isinstance(result, TemperatureMetrics)
                assert result.id == "temp:1"
                assert result.summary is not None
                # Summary is recomputed from visible sensors (one disk @ 30 °C).
                assert result.summary.average == 30.0
                assert result.summary.hottest is not None
                assert result.summary.hottest.name == "ST8000VN004"
                assert len(result.sensors) == 1
                assert result.sensors[0].name == "ST8000VN004"
                assert result.sensors[0].temperature == 30.0

    async def test_get_temperature_metrics_empty(self) -> None:
        """Test get_temperature_metrics with empty response."""
        from unraid_api.models import TemperatureMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"metrics": {}}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_temperature_metrics()

                assert isinstance(result, TemperatureMetrics)
                assert result.id is None
                assert result.sensors == []


class TestGetMetricsAuditFields:
    """Tests verifying get_metrics() returns active, buffcache, and per-cpu fields."""

    async def test_get_metrics_memory_active_buffcache(self) -> None:
        """Test get_metrics includes active and buffcache memory fields."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {"percentTotal": 25.0, "cpus": []},
                            "memory": {
                                "total": 16000000000,
                                "used": 8000000000,
                                "free": 8000000000,
                                "available": 12000000000,
                                "active": 6094684160,
                                "buffcache": 29019455488,
                                "percentTotal": 50.0,
                                "swapTotal": 4000000000,
                                "swapUsed": 1000000000,
                                "swapFree": 3000000000,
                                "percentSwapTotal": 25.0,
                            },
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_metrics()

                assert result["memory"]["active"] == 6094684160
                assert result["memory"]["buffcache"] == 29019455488

    async def test_get_metrics_per_cpu_fields(self) -> None:
        """Test get_metrics returns all per-cpu fields."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "cpu": {
                                "percentTotal": 25.0,
                                "cpus": [
                                    {
                                        "percentTotal": 30.0,
                                        "percentUser": 20.0,
                                        "percentSystem": 8.0,
                                        "percentIdle": 70.0,
                                        "percentNice": 0.5,
                                        "percentIrq": 0.1,
                                        "percentGuest": 0.0,
                                        "percentSteal": 0.0,
                                    }
                                ],
                            },
                            "memory": {"total": 16000000000},
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_metrics()

                cpu = result["cpu"]["cpus"][0]
                assert cpu["percentNice"] == 0.5
                assert cpu["percentIrq"] == 0.1
                assert cpu["percentGuest"] == 0.0
                assert cpu["percentSteal"] == 0.0


class TestGetNotificationsAuditFields:
    """Tests verifying get_notifications() returns link, type, formattedTimestamp."""

    async def test_get_notifications_all_fields(self) -> None:
        """Test get_notifications includes link, type, formattedTimestamp."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "notifications": {
                            "overview": {
                                "unread": {
                                    "info": 1,
                                    "warning": 0,
                                    "alert": 0,
                                    "total": 1,
                                },
                                "archive": {
                                    "info": 0,
                                    "warning": 0,
                                    "alert": 0,
                                    "total": 0,
                                },
                            },
                            "list": [
                                {
                                    "id": "n:1",
                                    "title": "Test",
                                    "subject": "Subject",
                                    "description": "Desc",
                                    "importance": "info",
                                    "link": "https://example.com/info",
                                    "type": "UNREAD",
                                    "timestamp": "2024-01-01T00:00:00Z",
                                    "formattedTimestamp": "Jan 1, 2024 12:00 AM",
                                }
                            ],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_notifications()

                notif = result["list"][0]
                assert notif["link"] == "https://example.com/info"
                assert notif["type"] == "UNREAD"
                assert notif["formattedTimestamp"] == "Jan 1, 2024 12:00 AM"


class TestGetPhysicalDisksAuditFields:
    """Tests for get_physical_disks() extended fields."""

    async def test_get_physical_disks_extended_fields(self) -> None:
        """Test get_physical_disks includes serialNum, firmwareRevision, partitions."""
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "disks": [
                            {
                                "id": "disk:sda",
                                "device": "sda",
                                "name": "WDC WD40EFAX",
                                "vendor": "WDC",
                                "size": 4000787030016,
                                "type": "HDD",
                                "interfaceType": "SATA",
                                "temperature": 35.0,
                                "isSpinning": True,
                                "serialNum": "WD-WX11A12B3456",
                                "firmwareRevision": "83.00A83",
                                "partitions": [
                                    {
                                        "name": "sda1",
                                        "fsType": "xfs",
                                        "size": 4000785088512,
                                    }
                                ],
                            }
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.get_physical_disks()

                disk = result[0]
                assert disk["serialNum"] == "WD-WX11A12B3456"
                assert disk["firmwareRevision"] == "83.00A83"
                assert len(disk["partitions"]) == 1
                assert disk["partitions"][0]["name"] == "sda1"


class TestTypedGetSharesCommentField:
    """Tests verifying typed_get_shares() queries and returns comment field."""

    async def test_typed_get_shares_comment(self) -> None:
        """Test typed_get_shares includes comment in results."""
        from unraid_api.models import Share

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "shares": [
                            {
                                "id": "share:appdata",
                                "name": "appdata",
                                "comment": "Application data storage",
                                "size": 0,
                                "used": 50000000,
                                "free": 100000000,
                            },
                        ]
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                result = await client.typed_get_shares()

                assert len(result) == 1
                assert isinstance(result[0], Share)
                assert result[0].comment == "Application data storage"


class TestNetworkQuery:
    """Tests for get_network / typed_get_network."""

    async def test_get_network_returns_raw_dict(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "network": {
                            "id": "network:default",
                            "accessUrls": [
                                {
                                    "type": "LAN",
                                    "name": "Tower",
                                    "ipv4": "http://192.168.1.10",
                                    "ipv6": None,
                                }
                            ],
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.get_network()
                assert result["id"] == "network:default"
                assert len(result["accessUrls"]) == 1
                assert result["accessUrls"][0]["type"] == "LAN"

    async def test_typed_get_network_returns_model(self) -> None:
        from unraid_api.models import Network

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "network": {
                            "id": "network:default",
                            "accessUrls": [
                                {
                                    "type": "LAN",
                                    "name": "Tower",
                                    "ipv4": "http://192.168.1.10",
                                    "ipv6": None,
                                },
                                {
                                    "type": "WAN",
                                    "name": None,
                                    "ipv4": "https://remote.example.com",
                                    "ipv6": None,
                                },
                            ],
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                net = await client.typed_get_network()
                assert isinstance(net, Network)
                assert net.id == "network:default"
                assert net.accessUrls is not None
                assert len(net.accessUrls) == 2
                assert net.accessUrls[0].type == "LAN"
                assert net.accessUrls[1].type == "WAN"
                assert net.accessUrls[1].ipv4 == "https://remote.example.com"


class TestCreateNotificationMutation:
    """Tests for createNotification / notifyIfUnique mutations."""

    async def test_create_notification_full_fields(self) -> None:
        from unraid_api.models import Notification

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "createNotification": {
                            "id": "notification:123",
                            "title": "HA Test",
                            "subject": "Ping",
                            "description": "Hello from Home Assistant",
                            "importance": "INFO",
                            "link": "https://ha.example.com",
                            "type": "UNREAD",
                            "timestamp": "2026-04-11T10:00:00Z",
                            "formattedTimestamp": "Apr 11 10:00",
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.create_notification(
                    title="HA Test",
                    subject="Ping",
                    description="Hello from Home Assistant",
                    importance="INFO",
                    link="https://ha.example.com",
                )
                assert isinstance(result, Notification)
                assert result.id == "notification:123"
                assert result.title == "HA Test"
                assert result.importance == "INFO"
                assert result.link == "https://ha.example.com"

    async def test_create_notification_without_link(self) -> None:
        from unraid_api.models import Notification

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "createNotification": {
                            "id": "notification:456",
                            "title": "Warning",
                            "subject": "Disk",
                            "description": "Disk 2 warning",
                            "importance": "WARNING",
                            "link": None,
                            "type": "UNREAD",
                            "timestamp": None,
                            "formattedTimestamp": None,
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.create_notification(
                    title="Warning",
                    subject="Disk",
                    description="Disk 2 warning",
                    importance="WARNING",
                )
                assert isinstance(result, Notification)
                assert result.importance == "WARNING"
                assert result.link is None

    async def test_notify_if_unique_returns_model_on_new(self) -> None:
        from unraid_api.models import Notification

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "notifyIfUnique": {
                            "id": "notification:789",
                            "title": "Unique",
                            "subject": "Test",
                            "description": "only once",
                            "importance": "INFO",
                            "link": None,
                            "type": "UNREAD",
                            "timestamp": None,
                            "formattedTimestamp": None,
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.notify_if_unique(
                    title="Unique",
                    subject="Test",
                    description="only once",
                    importance="INFO",
                )
                assert isinstance(result, Notification)
                assert result.id == "notification:789"

    async def test_notify_if_unique_returns_none_on_duplicate(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"notifyIfUnique": None}},
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.notify_if_unique(
                    title="Dup",
                    subject="Test",
                    description="already exists",
                    importance="INFO",
                )
                assert result is None


class TestUpdateTemperatureConfigMutation:
    """Tests for updateTemperatureConfig mutation."""

    async def test_update_temperature_config_passes_input(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            body = kwargs.get("json") or {}
            captured["body"] = body
            return CallbackResult(
                status=200,
                payload={"data": {"updateTemperatureConfig": True}},
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.update_temperature_config(
                    enabled=True,
                    polling_interval=60,
                    default_unit="CELSIUS",
                    thresholds={"cpu_warning": 70, "cpu_critical": 85},
                )

        assert result is True
        body = captured["body"]
        assert isinstance(body, dict)
        variables = body["variables"]
        assert isinstance(variables, dict)
        assert variables["input"]["enabled"] is True
        assert variables["input"]["polling_interval"] == 60
        assert variables["input"]["default_unit"] == "CELSIUS"
        assert variables["input"]["thresholds"]["cpu_warning"] == 70
        assert variables["input"]["thresholds"]["cpu_critical"] == 85


def _capabilities_payload(
    *,
    query_fields: list[str],
    mutation_fields: list[str] | None = None,
    subscription_fields: list[str] | None = None,
    docker_container_fields: list[str] | None = None,
    tailscale_fields: list[str] | None = None,
) -> dict[str, object]:
    """Build a minimal aliased __type introspection response."""

    def type_entry(name: str, fields: list[str] | None) -> dict[str, object] | None:
        if fields is None:
            return None
        return {"name": name, "fields": [{"name": f} for f in fields]}

    return {
        "data": {
            "Query": type_entry("Query", query_fields),
            "Mutation": type_entry("Mutation", mutation_fields or []),
            "Subscription": type_entry("Subscription", subscription_fields or []),
            "DockerContainer": type_entry("DockerContainer", docker_container_fields),
            "TailscaleStatus": type_entry("TailscaleStatus", tailscale_fields),
            "DockerNetwork": None,
            "Notification": None,
            "ParityCheck": None,
            "UnraidArray": None,
        }
    }


class TestCapabilitiesIntegration:
    """Tests for UnraidClient.get_capabilities lazy introspection."""

    async def test_get_capabilities_runs_introspection_once(self) -> None:
        """Subsequent calls return the cached capabilities object."""
        payload = _capabilities_payload(
            query_fields=["array", "network", "docker"],
            mutation_fields=["createNotification"],
        )
        async with aiointercept(mock_external_urls=True) as m:
            m.post("https://unraid.test/graphql", payload=payload)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._resolved_url = "https://unraid.test/graphql"
                caps_a = await client.get_capabilities()
                caps_b = await client.get_capabilities()

        assert caps_a is caps_b
        assert caps_a.has("Query.network") is True
        assert caps_a.has("Mutation.createNotification") is True
        assert caps_a.is_permissive is False

    async def test_get_capabilities_falls_back_to_permissive_on_error(self) -> None:
        """Introspection failure returns permissive capabilities, not an error."""
        async with aiointercept(mock_external_urls=True) as m:
            m.post(
                "https://unraid.test/graphql",
                payload={"errors": [{"message": "introspection disabled"}]},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._resolved_url = "https://unraid.test/graphql"
                caps = await client.get_capabilities()

        assert caps.is_permissive is True
        assert caps.has("Query.anything") is True

    async def test_get_capabilities_propagates_auth_error(self) -> None:
        """An auth failure during introspection should surface, not degrade."""
        async with aiointercept(mock_external_urls=True) as m:
            m.post("https://unraid.test/graphql", status=401)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._resolved_url = "https://unraid.test/graphql"
                with pytest.raises(UnraidAuthenticationError):
                    await client.get_capabilities()

        assert client._capabilities is None


class TestNewFeaturesCapabilityGating:
    """New top-level features must raise clean errors on old servers."""

    async def _client_with_missing(
        self,
        *,
        queries: list[str] | None = None,
        mutations: list[str] | None = None,
        subscriptions: list[str] | None = None,
    ) -> UnraidClient:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            _capabilities_payload(
                query_fields=queries or [],
                mutation_fields=mutations or [],
                subscription_fields=subscriptions or [],
            )["data"]
        )
        return client

    async def test_get_network_errors_when_missing(self) -> None:
        client = await self._client_with_missing(queries=["array"])
        with pytest.raises(UnraidAPIError, match="network"):
            await client.get_network()

    async def test_typed_get_network_errors_when_missing(self) -> None:
        client = await self._client_with_missing(queries=["array"])
        with pytest.raises(UnraidAPIError, match="network"):
            await client.typed_get_network()

    async def test_create_notification_errors_when_missing(self) -> None:
        client = await self._client_with_missing(mutations=["archiveAll"])
        with pytest.raises(UnraidAPIError, match="createNotification"):
            await client.create_notification(
                title="t", subject="s", description="d", importance="INFO"
            )

    async def test_notify_if_unique_errors_when_missing(self) -> None:
        client = await self._client_with_missing(mutations=["archiveAll"])
        with pytest.raises(UnraidAPIError, match="notifyIfUnique"):
            await client.notify_if_unique(
                title="t", subject="s", description="d", importance="INFO"
            )

    async def test_update_temperature_config_errors_when_missing(self) -> None:
        client = await self._client_with_missing(mutations=["archiveAll"])
        with pytest.raises(UnraidAPIError, match="updateTemperatureConfig"):
            await client.update_temperature_config(enabled=True)

    async def test_subscribe_notification_added_errors_when_missing(self) -> None:
        client = await self._client_with_missing(subscriptions=["arraySubscription"])
        with pytest.raises(UnraidAPIError, match="notificationAdded"):
            async for _ in client.subscribe_notification_added():
                pass

    async def test_subscribe_notifications_overview_errors_when_missing(self) -> None:
        client = await self._client_with_missing(subscriptions=["arraySubscription"])
        with pytest.raises(UnraidAPIError, match="notificationsOverview"):
            async for _ in client.subscribe_notifications_overview():
                pass

    async def test_subscribe_warnings_and_alerts_errors_when_missing(self) -> None:
        client = await self._client_with_missing(subscriptions=["arraySubscription"])
        with pytest.raises(UnraidAPIError, match="notificationsWarningsAndAlerts"):
            async for _ in client.subscribe_notifications_warnings_and_alerts():
                pass

    async def test_subscribe_parity_history_errors_when_missing(self) -> None:
        client = await self._client_with_missing(subscriptions=["arraySubscription"])
        with pytest.raises(UnraidAPIError, match="parityHistorySubscription"):
            async for _ in client.subscribe_parity_history():
                pass

    async def test_permissive_does_not_block(self) -> None:
        """Permissive capabilities (introspection failed) must not gate."""
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()
        # _require_capability must be a no-op in permissive mode
        client._require_capability("X", "Query.anything")


class TestTypedGetContainersCapabilityGating:
    """typed_get_containers composes its query from server capabilities."""

    async def _run_with_schema(
        self,
        docker_container_fields: list[str],
        tailscale_fields: list[str],
        container_response: dict[str, object],
    ) -> tuple[list[str], object]:
        captured: dict[str, object] = {}

        def capture(url: object, **kwargs: object) -> CallbackResult:
            body = kwargs.get("json")
            assert isinstance(body, dict)
            query_text = body.get("query", "")
            calls = captured.setdefault("queries", [])
            assert isinstance(calls, list)
            calls.append(query_text)
            # First call is introspection, second is containers query
            if len(calls) == 1:
                return CallbackResult(
                    payload=_capabilities_payload(
                        query_fields=["docker"],
                        docker_container_fields=docker_container_fields,
                        tailscale_fields=tailscale_fields,
                    )
                )
            return CallbackResult(
                payload={"data": {"docker": {"containers": [container_response]}}}
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.post("https://unraid.test/graphql", callback=capture, repeat=True)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._resolved_url = "https://unraid.test/graphql"
                containers = await client.typed_get_containers()

        calls = captured.get("queries")
        assert isinstance(calls, list)
        return [c for c in calls if isinstance(c, str)], containers

    async def test_old_server_omits_extended_fields(self) -> None:
        """On an older server without extended fields, query omits them."""
        core_fields = ["id", "names", "image", "state", "status", "autoStart", "ports"]
        queries, containers = await self._run_with_schema(
            docker_container_fields=core_fields,
            tailscale_fields=[],
            container_response={
                "id": "abc",
                "names": ["/foo"],
                "image": "nginx",
                "state": "RUNNING",
                "status": "Up",
                "autoStart": False,
                "ports": [],
            },
        )

        # Two POSTs — introspection + container query
        assert len(queries) == 2
        container_query = queries[1]
        assert "labels" not in container_query
        assert "networkSettings" not in container_query
        assert "mounts" not in container_query
        assert "isUpdateAvailable" not in container_query
        assert "tailscaleStatus" not in container_query
        assert "exitNodeStatus" not in container_query
        assert len(containers) == 1

    async def test_full_server_includes_all_fields(self) -> None:
        """On a current server, query requests every extended field."""
        full_container_fields = [
            "id",
            "names",
            "image",
            "imageId",
            "state",
            "status",
            "autoStart",
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
            "tailscaleStatus",
            "isRebuildReady",
            "templatePorts",
            "lanIpPorts",
            "hostConfig",
            "ports",
            "labels",
            "networkSettings",
            "mounts",
        ]
        full_tailscale_fields = [
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
            "exitNodeStatus",
            "webUiUrl",
            "keyExpiry",
            "keyExpiryDays",
            "keyExpired",
            "backendState",
            "authUrl",
        ]
        queries, containers = await self._run_with_schema(
            docker_container_fields=full_container_fields,
            tailscale_fields=full_tailscale_fields,
            container_response={
                "id": "abc",
                "names": ["/foo"],
                "image": "nginx",
                "state": "RUNNING",
                "status": "Up",
                "autoStart": False,
                "ports": [],
                "labels": {"io.foo": "bar"},
                "networkSettings": None,
                "mounts": None,
                "isUpdateAvailable": False,
                "tailscaleStatus": {"online": True, "version": "1.80.0"},
            },
        )

        container_query = queries[1]
        assert "labels" in container_query
        assert "networkSettings" in container_query
        assert "mounts" in container_query
        assert "isUpdateAvailable" in container_query
        assert "tailscaleStatus" in container_query
        assert "exitNodeStatus" in container_query
        assert "version" in container_query
        assert len(containers) == 1


# =============================================================================
# Unraid 7.3 / API 4.34.0 additions
# =============================================================================


class TestSystemTime:
    """Tests for system-time query/mutation methods (7.3)."""

    async def test_get_system_time_returns_model(self) -> None:
        from unraid_api.models import SystemTime

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "systemTime": {
                            "currentTime": "2026-06-01T04:47:38.377Z",
                            "ntpServers": ["time1.google.com", "time2.google.com"],
                            "timeZone": "Australia/Brisbane",
                            "useNtp": True,
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                st = await client.get_system_time()
                assert isinstance(st, SystemTime)
                assert st.timeZone == "Australia/Brisbane"
                assert st.useNtp is True
                assert st.ntpServers == ["time1.google.com", "time2.google.com"]

    async def test_get_timezone_options_returns_list(self) -> None:
        from unraid_api.models import TimeZoneOption

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "timeZoneOptions": [
                            {"label": "Brisbane", "value": "Australia/Brisbane"},
                            {"label": "UTC", "value": "UTC"},
                        ]
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                options = await client.get_timezone_options()
                assert len(options) == 2
                assert all(isinstance(o, TimeZoneOption) for o in options)
                assert options[0].value == "Australia/Brisbane"

    async def test_update_system_time_passes_only_set_fields(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "updateSystemTime": {
                            "currentTime": "2026-06-01T04:47:38.377Z",
                            "ntpServers": ["pool.ntp.org"],
                            "timeZone": "UTC",
                            "useNtp": True,
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities
                from unraid_api.models import SystemTime

                client._capabilities = ServerCapabilities.permissive()
                result = await client.update_system_time(
                    time_zone="UTC",
                    use_ntp=True,
                    ntp_servers=["pool.ntp.org"],
                )
                assert isinstance(result, SystemTime)
                assert result.timeZone == "UTC"

        body = captured["body"]
        assert isinstance(body, dict)
        variables = body["variables"]
        assert variables["input"]["timeZone"] == "UTC"
        assert variables["input"]["useNtp"] is True
        assert variables["input"]["ntpServers"] == ["pool.ntp.org"]
        # Unset field must be omitted entirely
        assert "manualDateTime" not in variables["input"]

    async def test_get_system_time_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Query": {"name": "Query", "fields": [{"name": "array"}]}}
        )
        with pytest.raises(UnraidAPIError, match=r"[Ss]ystem time"):
            await client.get_system_time()

    async def test_update_system_time_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Mutation": {"name": "Mutation", "fields": [{"name": "archiveAll"}]}}
        )
        with pytest.raises(UnraidAPIError, match="updateSystemTime"):
            await client.update_system_time(time_zone="UTC")

    async def test_get_timezone_options_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Query": {"name": "Query", "fields": [{"name": "array"}]}}
        )
        with pytest.raises(UnraidAPIError, match=r"[Tt]ime-zone options"):
            await client.get_timezone_options()


class TestDiskAndUpsExtras:
    """Tests for disk/UPS extra accessors (7.3)."""

    async def test_get_assignable_disks_returns_models(self) -> None:
        from unraid_api.models import PhysicalDisk

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "assignableDisks": [
                            {
                                "id": "disk:sdb",
                                "device": "sdb",
                                "name": "ST4000",
                                "size": 4000787030016,
                                "isSpinning": True,
                            }
                        ]
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                disks = await client.get_assignable_disks()
                assert len(disks) == 1
                assert isinstance(disks[0], PhysicalDisk)
                assert disks[0].id == "disk:sdb"

    async def test_get_assignable_disks_empty(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"assignableDisks": []}},
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                assert await client.get_assignable_disks() == []

    async def test_get_disk_returns_model(self) -> None:
        from unraid_api.models import PhysicalDisk

        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "disk": {
                            "id": "disk:sda",
                            "device": "sda",
                            "name": "Samsung",
                            "smartStatus": "OK",
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                disk = await client.get_disk("disk:sda")
                assert isinstance(disk, PhysicalDisk)
                assert disk.id == "disk:sda"

        assert captured["body"]["variables"]["id"] == "disk:sda"  # type: ignore[index]

    async def test_typed_get_ups_device_returns_model(self) -> None:
        from unraid_api.models import UPSDevice

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "upsDeviceById": {
                            "id": "ups:1",
                            "name": "APC",
                            "model": "Back-UPS",
                            "status": "ONLINE",
                            "battery": {"chargeLevel": 100},
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                ups = await client.typed_get_ups_device("ups:1")
                assert isinstance(ups, UPSDevice)
                assert ups.id == "ups:1"

    async def test_typed_get_ups_device_returns_none(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"upsDeviceById": None}},
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                assert await client.typed_get_ups_device("ups:absent") is None

    async def test_get_assignable_disks_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Query": {"name": "Query", "fields": [{"name": "array"}]}}
        )
        with pytest.raises(UnraidAPIError, match="assignableDisks"):
            await client.get_assignable_disks()


class TestSubscribeDisplay:
    """Tests for the displaySubscription wrapper (7.3)."""

    async def test_subscribe_display_yields_display_settings(self) -> None:
        from unraid_api.capabilities import ServerCapabilities
        from unraid_api.models import DisplaySettings

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()

        async def fake_subscribe(subscription, variables=None):  # type: ignore[no-untyped-def]
            assert "displaySubscription" in subscription
            yield {"displaySubscription": {"theme": "black", "unit": "CELSIUS"}}

        client.subscribe = fake_subscribe  # type: ignore[assignment]

        results = [s async for s in client.subscribe_display()]
        assert len(results) == 1
        assert isinstance(results[0], DisplaySettings)
        assert results[0].theme == "black"
        assert results[0].unit == "CELSIUS"

    async def test_subscribe_display_handles_missing_payload(self) -> None:
        from unraid_api.capabilities import ServerCapabilities
        from unraid_api.models import DisplaySettings

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()

        async def fake_subscribe(subscription, variables=None):  # type: ignore[no-untyped-def]
            yield {}  # event without a displaySubscription key

        client.subscribe = fake_subscribe  # type: ignore[assignment]

        results = [s async for s in client.subscribe_display()]
        assert len(results) == 1
        assert isinstance(results[0], DisplaySettings)
        assert results[0].theme is None

    async def test_subscribe_display_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Subscription": {"name": "Subscription", "fields": [{"name": "logFile"}]}}
        )
        with pytest.raises(UnraidAPIError, match="displaySubscription"):
            _ = [s async for s in client.subscribe_display()]


class TestCuratedAdmin:
    """Tests for curated Tier-3 methods: get_settings + configure_ups (7.3)."""

    async def test_get_settings_returns_model(self) -> None:
        from unraid_api.models import Settings

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "settings": {
                            "id": "settings",
                            "api": {
                                "version": "4.34.0",
                                "sandbox": False,
                                "plugins": ["unraid-api-plugin-connect"],
                                "extraOrigins": [],
                                "ssoSubIds": [],
                            },
                            "unified": {
                                "values": {"foo": "bar"},
                                "dataSchema": {},
                                "uiSchema": {},
                            },
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                settings = await client.get_settings()
                assert isinstance(settings, Settings)
                assert settings.api is not None
                assert settings.api.version == "4.34.0"
                assert settings.api.sandbox is False
                assert settings.unified is not None
                assert settings.unified.values == {"foo": "bar"}

    async def test_configure_ups_passes_only_set_fields(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(status=200, payload={"data": {"configureUps": True}})

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                ok = await client.configure_ups(
                    service="ENABLE",
                    ups_type="USB",
                    battery_level=10,
                    minutes=5,
                )
                assert ok is True

        variables = captured["body"]["variables"]  # type: ignore[index]
        cfg = variables["config"]
        assert cfg["service"] == "ENABLE"
        assert cfg["upsType"] == "USB"
        assert cfg["batteryLevel"] == 10
        assert cfg["minutes"] == 5
        assert "device" not in cfg
        assert "killUps" not in cfg

    async def test_get_settings_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Query": {"name": "Query", "fields": [{"name": "array"}]}}
        )
        with pytest.raises(UnraidAPIError, match=r"[Ss]ettings"):
            await client.get_settings()

    async def test_configure_ups_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Mutation": {"name": "Mutation", "fields": [{"name": "archiveAll"}]}}
        )
        with pytest.raises(UnraidAPIError, match="configureUps"):
            await client.configure_ups(service="DISABLE")


class TestSystemTimeAndUpsAllFields:
    """Branch coverage: every optional input field is serialized."""

    async def test_update_system_time_with_manual_datetime(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "updateSystemTime": {
                            "currentTime": "2026-06-01T00:00:00Z",
                            "ntpServers": [],
                            "timeZone": "UTC",
                            "useNtp": False,
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                await client.update_system_time(
                    use_ntp=False, manual_date_time="2026-06-01T00:00:00Z"
                )

        cfg = captured["body"]["variables"]["input"]  # type: ignore[index]
        assert cfg["useNtp"] is False
        assert cfg["manualDateTime"] == "2026-06-01T00:00:00Z"
        assert "timeZone" not in cfg
        assert "ntpServers" not in cfg

    async def test_configure_ups_all_fields(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(status=200, payload={"data": {"configureUps": True}})

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                ok = await client.configure_ups(
                    service="ENABLE",
                    ups_cable="USB_CUSTOM",
                    custom_ups_cable="custom-cable",
                    ups_type="USB",
                    device="/dev/usb",
                    override_ups_capacity=1500,
                    battery_level=20,
                    minutes=10,
                    timeout=30,
                    kill_ups="YES",
                )
                assert ok is True

        cfg = captured["body"]["variables"]["config"]  # type: ignore[index]
        assert cfg == {
            "service": "ENABLE",
            "upsCable": "USB_CUSTOM",
            "customUpsCable": "custom-cable",
            "upsType": "USB",
            "device": "/dev/usb",
            "overrideUpsCapacity": 1500,
            "batteryLevel": 20,
            "minutes": 10,
            "timeout": 30,
            "killUps": "YES",
        }


# =============================================================================
# API 4.35.0 additions
# =============================================================================


class TestNetworkMetrics:
    """Tests for get_network_metrics (metrics.network, API 4.35.0+)."""

    async def test_get_network_metrics_returns_models(self) -> None:
        from unraid_api.models import NetworkMetrics

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "metrics": {
                            "network": [
                                {
                                    "id": "server:metrics/network/br0",
                                    "name": "br0",
                                    "rxSec": 9474.57,
                                    "txSec": 30745.68,
                                    "operstate": "up",
                                    "bytesReceived": 383537817199,
                                    "bytesSent": 61471810463,
                                    "packetsReceived": 172645744,
                                    "packetsSent": 42097920,
                                    "receiveErrors": 0,
                                    "transmitErrors": 0,
                                    "receiveDropped": 3771,
                                    "transmitDropped": 6,
                                },
                                {
                                    "id": "server:metrics/network/lo",
                                    "name": "lo",
                                    "rxSec": 542.83,
                                    "txSec": 542.83,
                                    "operstate": "unknown",
                                    "bytesReceived": 733407314,
                                    "bytesSent": 733407314,
                                    "packetsReceived": 5614820,
                                    "packetsSent": 5614820,
                                },
                            ]
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.get_network_metrics()

                assert isinstance(result, list)
                assert len(result) == 2
                assert all(isinstance(n, NetworkMetrics) for n in result)
                br0 = result[0]
                assert br0.name == "br0"
                assert br0.operstate == "up"
                assert br0.rxSec == 9474.57
                assert br0.txSec == 30745.68
                assert br0.bytesReceived == 383537817199
                assert br0.bytesSent == 61471810463
                assert br0.packetsReceived == 172645744
                assert br0.packetsSent == 42097920
                assert br0.receiveErrors == 0
                assert br0.transmitErrors == 0
                assert br0.receiveDropped == 3771
                assert br0.transmitDropped == 6

    async def test_get_network_metrics_empty(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"metrics": {"network": []}}},
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.get_network_metrics()

                assert result == []

    async def test_get_network_metrics_errors_when_missing(self) -> None:
        """Older servers without Metrics.network raise UnraidAPIError."""
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {
                # Query.metrics exists, but Metrics lacks the network field —
                # the gate must check Metrics.network specifically.
                "Query": {"name": "Query", "fields": [{"name": "metrics"}]},
                "Metrics": {"name": "Metrics", "fields": [{"name": "cpu"}]},
            }
        )
        with pytest.raises(UnraidAPIError, match=r"[Nn]etwork metrics"):
            await client.get_network_metrics()

    async def test_get_network_metrics_query_shape(self) -> None:
        """Query must target metrics.network with the 4.35.0 field set."""
        captured_requests: list[str] = []

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            body = kwargs.get("json") or {}
            captured_requests.append(body.get("query", ""))
            return CallbackResult(
                status=200,
                payload={"data": {"metrics": {"network": []}}},
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                await client.get_network_metrics()

        assert captured_requests, "no GraphQL request was captured"
        query = captured_requests[0]
        assert re.search(r"\bmetrics\b\s*\{\s*\bnetwork\b\s*\{", query), (
            "query must target metrics.network"
        )
        for needed in (
            "id",
            "name",
            "rxSec",
            "txSec",
            "operstate",
            "bytesReceived",
            "bytesSent",
            "packetsReceived",
            "packetsSent",
            "receiveErrors",
            "transmitErrors",
            "receiveDropped",
            "transmitDropped",
        ):
            assert needed in query, f"{needed} not in query"


class TestSubscribeNetworkMetrics:
    """Tests for the systemMetricsNetwork subscription wrapper (4.35.0)."""

    async def test_subscribe_network_metrics_yields_models(self) -> None:
        from unraid_api.capabilities import ServerCapabilities
        from unraid_api.models import NetworkMetrics

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()

        async def fake_subscribe(subscription, variables=None):  # type: ignore[no-untyped-def]
            assert "systemMetricsNetwork" in subscription
            yield {
                "systemMetricsNetwork": [
                    {
                        "id": "server:metrics/network/br0",
                        "name": "br0",
                        "rxSec": 1000.0,
                        "txSec": 2000.0,
                        "operstate": "up",
                        "bytesReceived": 100,
                        "bytesSent": 200,
                    },
                    {
                        "id": "server:metrics/network/eth0",
                        "name": "eth0",
                        "rxSec": 0.0,
                        "txSec": 0.0,
                        "operstate": "down",
                    },
                ]
            }

        client.subscribe = fake_subscribe  # type: ignore[assignment]

        results = [n async for n in client.subscribe_network_metrics()]
        assert len(results) == 1
        interfaces = results[0]
        assert isinstance(interfaces, list)
        assert len(interfaces) == 2
        assert all(isinstance(i, NetworkMetrics) for i in interfaces)
        assert interfaces[0].name == "br0"
        assert interfaces[0].rxSec == 1000.0
        assert interfaces[1].operstate == "down"

    async def test_subscribe_network_metrics_handles_missing_payload(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()

        async def fake_subscribe(subscription, variables=None):  # type: ignore[no-untyped-def]
            yield {}  # event without a systemMetricsNetwork key

        client.subscribe = fake_subscribe  # type: ignore[assignment]

        results = [n async for n in client.subscribe_network_metrics()]
        assert results == [[]]

    async def test_subscribe_network_metrics_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Subscription": {"name": "Subscription", "fields": [{"name": "logFile"}]}}
        )
        with pytest.raises(UnraidAPIError, match="systemMetricsNetwork"):
            _ = [n async for n in client.subscribe_network_metrics()]


class TestDockerBulkUpdateMethods:
    """Tests for updateAllContainers/updateContainers/refreshDockerDigests."""

    async def test_update_all_containers(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "docker": {
                            "updateAllContainers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plex:latest",
                                    "state": "running",
                                },
                                {
                                    "id": "container:def456",
                                    "names": ["/sonarr"],
                                    "image": "sonarr:latest",
                                    "state": "running",
                                },
                            ]
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.update_all_containers()

                updated = result["docker"]["updateAllContainers"]
                assert len(updated) == 2
                assert updated[0]["image"] == "plex:latest"

    async def test_update_all_containers_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {
                "DockerMutations": {
                    "name": "DockerMutations",
                    "fields": [{"name": "start"}],
                }
            }
        )
        with pytest.raises(UnraidAPIError, match="updateAllContainers"):
            await client.update_all_containers()

    async def test_update_containers_passes_ids(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(
                status=200,
                payload={
                    "data": {
                        "docker": {
                            "updateContainers": [
                                {
                                    "id": "container:abc123",
                                    "names": ["/plex"],
                                    "image": "plex:latest",
                                    "state": "running",
                                },
                            ]
                        }
                    }
                },
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.update_containers(["container:abc123"])

                updated = result["docker"]["updateContainers"]
                assert len(updated) == 1

        body = captured["body"]
        assert isinstance(body, dict)
        assert body["variables"] == {"ids": ["container:abc123"]}

    async def test_update_containers_rejects_empty_list(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()
        with pytest.raises(ValueError, match="container_ids"):
            await client.update_containers([])

    async def test_update_containers_rejects_blank_ids(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.permissive()
        with pytest.raises(ValueError, match="container_ids"):
            await client.update_containers(["container:abc123", "  "])

    async def test_update_containers_trims_and_dedupes_ids(self) -> None:
        captured: dict[str, object] = {}

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            captured["body"] = kwargs.get("json") or {}
            return CallbackResult(
                status=200,
                payload={"data": {"docker": {"updateContainers": []}}},
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                await client.update_containers(
                    [" container:abc123 ", "container:def456", "container:abc123"]
                )

        body = captured["body"]
        assert isinstance(body, dict)
        assert body["variables"] == {"ids": ["container:abc123", "container:def456"]}

    async def test_update_containers_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {
                "DockerMutations": {
                    "name": "DockerMutations",
                    "fields": [{"name": "start"}],
                }
            }
        )
        with pytest.raises(UnraidAPIError, match="updateContainers"):
            await client.update_containers(["container:abc123"])

    async def test_refresh_docker_digests(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"refreshDockerDigests": True}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                from unraid_api.capabilities import ServerCapabilities

                client._capabilities = ServerCapabilities.permissive()
                result = await client.refresh_docker_digests()

                assert result is True

    async def test_refresh_docker_digests_errors_when_missing(self) -> None:
        from unraid_api.capabilities import ServerCapabilities

        client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
        client._capabilities = ServerCapabilities.from_introspection_response(
            {"Mutation": {"name": "Mutation", "fields": [{"name": "archiveAll"}]}}
        )
        with pytest.raises(UnraidAPIError, match="refreshDockerDigests"):
            await client.refresh_docker_digests()


# =============================================================================
# v4.37.x Client Methods Tests
# =============================================================================


class TestNetworkInterfacesMethods:
    """Tests for get_network_interfaces and typed_get_network_interfaces."""

    async def test_get_network_interfaces(self) -> None:
        payload = {
            "data": {
                "networkInterfaces": [
                    {
                        "id": "interface:eth0",
                        "name": "eth0",
                        "description": "NIC 1",
                        "ipAddress": "192.168.1.50",
                        "macAddress": "00:11:22:33:44:55",
                        "speed": 1000,
                        "status": "UP",
                    }
                ]
            }
        }
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", payload=payload)
            m.post("http://unraid.test/graphql", payload=payload)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                res = await client.get_network_interfaces()
                assert len(res) == 1
                assert res[0]["name"] == "eth0"
                assert res[0]["macAddress"] == "00:11:22:33:44:55"

                typed_res = await client.typed_get_network_interfaces()
                assert len(typed_res) == 1
                assert typed_res[0].name == "eth0"
                assert typed_res[0].speed == 1000
                assert typed_res[0].macAddress == "00:11:22:33:44:55"
                assert typed_res[0].mac == "00:11:22:33:44:55"


class TestDockerOrganizerMethods:
    """Tests for Docker organizer queries and folder mutations."""

    async def test_docker_organizer_methods(self) -> None:
        org_payload = {
            "data": {
                "docker": {
                    "organizer": {
                        "version": 1.0,
                        "views": [{"id": "view:1", "name": "Main", "flatEntries": []}],
                    }
                }
            }
        }
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", payload=org_payload)
            m.post("http://unraid.test/graphql", payload=org_payload)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "createDockerFolder": {
                            "version": 1.0,
                            "views": [
                                {"id": "view:1", "name": "Main", "flatEntries": []}
                            ],
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "renameDockerFolder": {
                            "version": 1.0,
                            "views": [
                                {"id": "view:1", "name": "Renamed", "flatEntries": []}
                            ],
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "deleteDockerEntries": {
                            "version": 1.0,
                            "views": [
                                {"id": "view:1", "name": "Main", "flatEntries": []}
                            ],
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "moveDockerEntriesToFolder": {
                            "version": 1.0,
                            "views": [
                                {"id": "view:1", "name": "Main", "flatEntries": []}
                            ],
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                org = await client.get_docker_organizer()
                assert org["version"] == 1.0

                typed_org = await client.typed_get_docker_organizer()
                assert typed_org.version == 1.0

                created = await client.create_docker_folder(
                    "Media", children_ids=["c1"]
                )
                assert created.version == 1.0

                renamed = await client.rename_docker_folder("folder:1", "NewMedia")
                assert renamed.views[0].name == "Renamed"

                deleted = await client.delete_docker_entries(["folder:1"])
                assert deleted.version == 1.0

                moved = await client.move_docker_entries_to_folder(["c1"], "folder:2")
                assert moved.version == 1.0


class TestArrayDiskMutations:
    """Tests for mount, unmount, and clear statistics disk mutations."""

    async def test_array_disk_mutations(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "mountArrayDisk": {
                                "id": "disk:1",
                                "name": "disk1",
                                "status": "DISK_OK",
                                "isSpinning": True,
                            }
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "unmountArrayDisk": {
                                "id": "disk:1",
                                "name": "disk1",
                                "status": "DISK_NP",
                                "isSpinning": False,
                            }
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "array": {
                            "clearArrayDiskStatistics": True,
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                mounted = await client.mount_array_disk("disk:1")
                assert mounted is not None
                assert mounted.isSpinning is True

                unmounted = await client.unmount_array_disk("disk:1")
                assert unmounted is not None
                assert unmounted.isSpinning is False

                cleared = await client.clear_array_disk_statistics("disk:1")
                assert cleared is True


class TestPluginOperationsMethods:
    """Tests for plugin queries and background operation tracking."""

    async def test_plugin_methods(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "installedUnraidPlugins": [
                            "community.applications.plg",
                            "unassigned.devices.plg",
                        ]
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "pluginInstallOperations": [
                            {"id": "op:1", "name": "test.plg", "status": "COMPLETED"}
                        ]
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "pluginInstallOperation": {
                            "id": "op:1",
                            "name": "test.plg",
                            "status": "COMPLETED",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                installed = await client.get_installed_unraid_plugins()
                assert len(installed) == 2
                assert installed[0] == "community.applications.plg"

                ops = await client.get_plugin_install_operations()
                assert len(ops) == 1
                assert ops[0].status == "COMPLETED"

                op = await client.get_plugin_install_operation("op:1")
                assert op is not None
                assert op.id == "op:1"


class TestServerMethods:
    """Tests for server query and update methods."""

    async def test_server_methods(self) -> None:
        servers_payload = {
            "data": {
                "servers": [{"id": "server:1", "name": "Tower", "status": "ONLINE"}]
            }
        }
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", payload=servers_payload)
            m.post("http://unraid.test/graphql", payload=servers_payload)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "server": {
                            "id": "server:1",
                            "name": "Tower",
                            "status": "ONLINE",
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "server": {
                            "id": "server:1",
                            "name": "Tower",
                            "status": "ONLINE",
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"server": None}},
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "updateServerIdentity": {
                            "id": "server:1",
                            "name": "Tower-Updated",
                            "status": "ONLINE",
                        }
                    }
                },
            )
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "updateServerIdentity": {
                            "id": "server:1",
                            "name": "Tower",
                            "status": "ONLINE",
                        }
                    }
                },
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                servers = await client.get_servers()
                assert len(servers) == 1
                assert servers[0]["name"] == "Tower"

                typed_servers = await client.typed_get_servers()
                assert len(typed_servers) == 1
                assert typed_servers[0].name == "Tower"

                server_raw = await client.get_server()
                assert isinstance(server_raw, dict)
                assert server_raw["id"] == "server:1"

                typed_server = await client.typed_get_server()
                assert typed_server is not None
                assert typed_server.id == "server:1"

                none_server = await client.typed_get_server()
                assert none_server is None

                updated = await client.update_server_identity(
                    name="Tower-Updated",
                    comment="Primary NAS",
                    sys_model="Custom Build",
                )
                assert updated.name == "Tower-Updated"

                updated_empty = await client.update_server_identity()
                assert updated_empty.name == "Tower"


class TestNotificationBatchMutations:
    """Tests for bulk notification archive, unarchive, and recalculate."""

    async def test_batch_notification_mutations(self) -> None:
        overview_data = {
            "unread": {"total": 0, "info": 0, "warning": 0, "alert": 0},
            "archive": {"total": 5, "info": 3, "warning": 1, "alert": 1},
        }
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"archiveNotifications": overview_data}},
            )
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"unarchiveNotifications": overview_data}},
            )
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"unarchiveAll": overview_data}},
            )
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"recalculateOverview": overview_data}},
            )

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                archived = await client.archive_notifications(["n1", "n2"])
                assert archived.archive.total == 5

                unarchived = await client.unarchive_notifications(["n1"])
                assert unarchived.archive.total == 5

                all_unarchived = await client.unarchive_all_notifications()
                assert all_unarchived.archive.total == 5

                recalculated = await client.recalculate_notification_overview()
                assert recalculated.archive.total == 5


class TestContainerAutostartMutation:
    """Tests for update_container_autostart."""

    async def test_update_container_autostart(self) -> None:
        """Verify update_container_autostart uses DockerAutostartEntryInput."""
        captured_requests: list[str] = []

        async def capture(url, **kwargs):  # type: ignore[no-untyped-def]
            """Capture outgoing GraphQL query for assertion."""
            body = kwargs.get("json") or {}
            captured_requests.append(body.get("query", ""))
            return CallbackResult(
                status=200,
                payload={"data": {"docker": {"updateAutostartConfiguration": True}}},
            )

        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post("http://unraid.test/graphql", callback=capture)

            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                res = await client.update_container_autostart(
                    [
                        {
                            "id": "container:1",
                            "autoStart": True,
                            "autoStartOrder": 1,
                            "autoStartWait": 0,
                        }
                    ]
                )
                assert res is True

        assert captured_requests, "no GraphQL request was captured"
        assert "$entries: [DockerAutostartEntryInput!]!" in captured_requests[0]
        assert "AutostartConfigurationEntryInput" not in captured_requests[0]


class TestStandbySafeTemperatureMetrics:
    """The safety signal uses API versions, independently of schema fallbacks."""

    @pytest.mark.parametrize(
        ("api", "expected"),
        [
            ("4.37.5", False),
            ("4.37.6", True),
            ("4.37.7", True),
            ("5.0.0", True),
            ("4.37.6rc1", False),
            ("4.37.6+build", True),
            ("unknown", False),
            ("not-a-version", False),
            ("", False),
        ],
    )
    async def test_versions(self, api: str, expected: bool) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            m.post(
                "http://unraid.test/graphql",
                payload={
                    "data": {
                        "info": {
                            "versions": {"core": {"api": api, "unraid": "unknown"}}
                        }
                    }
                },
            )
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                client._capabilities = ServerCapabilities.permissive()
                assert (
                    await client.supports_standby_safe_temperature_metrics() is expected
                )

    async def test_supplied_version_avoids_request(self) -> None:
        from unraid_api import MIN_STANDBY_SAFE_TEMPERATURE_API_VERSION
        from unraid_api.models import VersionInfo

        assert MIN_STANDBY_SAFE_TEMPERATURE_API_VERSION == "4.37.6"
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(client, "query", new_callable=AsyncMock) as query:
            for unraid in ("1.0", "unknown"):
                assert await client.supports_standby_safe_temperature_metrics(
                    VersionInfo(api="4.37.6", unraid=unraid)
                )
            query.assert_not_called()

    async def test_uncached(self) -> None:
        from unraid_api.models import VersionInfo

        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client,
            "get_version",
            side_effect=[
                VersionInfo(api="4.37.5", unraid="7.3"),
                VersionInfo(api="4.37.6", unraid="7.3"),
            ],
        ) as get_version:
            assert not await client.supports_standby_safe_temperature_metrics()
            assert await client.supports_standby_safe_temperature_metrics()
            assert get_version.await_count == 2

    @pytest.mark.parametrize("failure", [401, "connection"])
    async def test_request_errors_propagate(self, failure: int | str) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get("http://unraid.test/graphql", status=400)
            if failure == 401:
                m.post("http://unraid.test/graphql", status=401)
                expected = UnraidAuthenticationError
            else:
                m.post(
                    "http://unraid.test/graphql",
                    exception=aiohttp.ClientConnectionError(),
                )
                expected = UnraidConnectionError
            async with UnraidClient(
                "unraid.test", "test-key", verify_ssl=False
            ) as client:
                with pytest.raises(expected):
                    await client.supports_standby_safe_temperature_metrics()

    @pytest.mark.parametrize("safe", [False, True])
    async def test_query_split(self, safe: bool) -> None:
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client, "query", new_callable=AsyncMock, return_value={}
        ) as query:
            if safe:
                await client.get_system_metrics_safe()
            else:
                await client.get_system_metrics()
            text = query.call_args.args[0]
            assert ("temperature" in text) is not safe
            assert "packages { temp totalPower }" in text

    async def test_disk_fallback_id_parses(self) -> None:
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client,
            "query",
            new_callable=AsyncMock,
            return_value={
                "metrics": {
                    "temperature": {
                        "id": "temperature",
                        "sensors": [
                            {
                                "id": "disk:/dev/sdb",
                                "name": "USB Disk",
                                "type": "DISK",
                                "current": {"value": 32, "unit": "CELSIUS"},
                            }
                        ],
                    }
                }
            },
        ):
            result = await client.get_temperature_metrics()
            assert result.sensors[0].id == "disk:/dev/sdb"
            assert result.sensors[0].current.value == 32


class TestGraphQLAuthorizationCodes:
    """Ticket-defined authorization codes preserve partial-data behavior."""

    @pytest.mark.parametrize(
        "code", ["FORBIDDEN", "UNAUTHORIZED", "forbidden", "unauthorized"]
    )
    async def test_authorization(self, code: str) -> None:
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            return_value={
                "data": None,
                "errors": [
                    {
                        "message": "Denied",
                        "path": ["info"],
                        "extensions": {"code": code},
                    }
                ],
            },
        ):
            with pytest.raises(UnraidAuthenticationError, match=code.upper()) as exc:
                await client.query("query { info { os { hostname } } }")
            assert isinstance(exc.value, UnraidAPIError)
            assert "Denied (path:" in str(exc.value)

    async def test_partial_data_returned(self) -> None:
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            return_value={
                "data": {"online": True},
                "errors": [{"message": "Denied", "extensions": {"code": "FORBIDDEN"}}],
            },
        ):
            assert await client.query("query { online }") == {"online": True}

    @pytest.mark.parametrize(
        "error",
        [
            "Denied",
            {"message": "Denied"},
            {"extensions": None},
            {"extensions": "bad"},
            {"extensions": {}},
            {"extensions": {"code": 403}},
            {"extensions": {"code": "OTHER"}},
        ],
    )
    async def test_malformed_or_other_errors(self, error: object) -> None:
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            return_value={"errors": [error]},
        ):
            with pytest.raises(UnraidAPIError) as exc:
                await client.query("query { online }")
            assert type(exc.value) is UnraidAPIError

    async def test_introspection_denial_not_cached(self) -> None:
        client = UnraidClient("unraid.test", "test-key")
        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            return_value={
                "errors": [{"message": "Denied", "extensions": {"code": "FORBIDDEN"}}]
            },
        ):
            with pytest.raises(UnraidAuthenticationError):
                await client.get_capabilities()
            assert client._capabilities is None


class TestAPI437Alignment:
    """Server-dependent operations select only the supported schema paths."""

    @pytest.mark.parametrize("permissive", [False, True])
    async def test_native_restart(self, permissive: bool) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = (
            ServerCapabilities.permissive()
            if permissive
            else ServerCapabilities({"DockerMutations": frozenset({"restart"})})
        )
        response = {"docker": {"restart": {"id": "container:one", "state": "RUNNING"}}}
        with (
            patch.object(
                client, "mutate", new_callable=AsyncMock, return_value=response
            ) as mutate,
            patch.object(client, "stop_container", new_callable=AsyncMock) as stop,
            patch.object(client, "start_container", new_callable=AsyncMock) as start,
            patch("unraid_api.client.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            assert await client.restart_container("container:one", delay=5) == response
            mutate.assert_awaited_once()
            assert "restart(id: $id)" in mutate.call_args.args[0]
            assert mutate.call_args.args[1] == {"id": "container:one"}
            stop.assert_not_called()
            start.assert_not_called()
            sleep.assert_not_called()

    async def test_restart_fallback_order_and_delay(self) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities({})
        calls = MagicMock()
        with (
            patch.object(client, "stop_container", new_callable=AsyncMock) as stop,
            patch.object(
                client,
                "start_container",
                new_callable=AsyncMock,
                return_value={"docker": {"start": {}}},
            ) as start,
            patch("unraid_api.client.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            calls.attach_mock(stop, "stop")
            calls.attach_mock(sleep, "sleep")
            calls.attach_mock(start, "start")
            assert await client.restart_container("container:one", delay=2.5) == {
                "docker": {"start": {}}
            }
            assert [c[0] for c in calls.mock_calls] == ["stop", "sleep", "start"]
            sleep.assert_awaited_once_with(2.5)

    async def test_retired_removal_never_mutates(self) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities({})
        with patch.object(client, "mutate", new_callable=AsyncMock) as mutate:
            with (
                pytest.warns(DeprecationWarning) as warnings_seen,
                pytest.raises(UnraidAPIError, match="Core's storage workflow"),
            ):
                await client.remove_array_disk("disk:sdb")
            assert warnings_seen[0].filename == __file__
            mutate.assert_not_called()

    async def test_legacy_removal(self) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities(
            {"ArrayMutations": frozenset({"removeDiskFromArray"})}
        )
        with patch.object(
            client, "mutate", new_callable=AsyncMock, return_value={"array": {}}
        ) as mutate:
            with pytest.warns(DeprecationWarning):
                assert await client.remove_array_disk("disk:sdb", slot=4) == {
                    "array": {}
                }
            assert "removeDiskFromArray(input: $input)" in mutate.call_args.args[0]
            assert mutate.call_args.args[1] == {"input": {"id": "disk:sdb", "slot": 4}}

    @pytest.mark.parametrize(
        ("password", "keyfile"),
        [
            (None, None),
            ("example-password", None),
            (None, "ZXhhbXBsZQ=="),
            ("example-password", "ZXhhbXBsZQ=="),
            ("", ""),
        ],
    )
    async def test_array_start_variables(
        self, password: str | None, keyfile: str | None
    ) -> None:
        client = UnraidClient("unraid.test", "test-key")
        method = "mutate" if password is None and keyfile is None else "_execute_query"
        with patch.object(
            client,
            method,
            new_callable=AsyncMock,
            return_value={"array": {"state": "STARTED"}},
        ) as mutate:
            await client.start_array(
                decryption_password=password, decryption_keyfile=keyfile
            )
            text = mutate.call_args.args[0]
            if password is None and keyfile is None:
                assert "setState(input: { desiredState: START })" in text
                assert len(mutate.call_args.args) == 1
            else:
                expected = {"desiredState": "START"}
                if password is not None:
                    expected["decryptionPassword"] = password
                if keyfile is not None:
                    expected["decryptionKeyfile"] = keyfile
                assert mutate.call_args.args[1] == {"input": expected}
                assert "$input: ArrayStateInput!" in text
                assert mutate.call_args.kwargs == {"require_https": True}
                for secret in (password, keyfile):
                    if secret:
                        assert secret not in text

    @pytest.mark.parametrize(
        ("method", "field"),
        [("install_plugin", "installPlugin"), ("install_language", "installLanguage")],
    )
    @pytest.mark.parametrize(
        "options", [{}, {"name": "Example", "forced": False}, {"forced": True}]
    )
    async def test_install(
        self, method: str, field: str, options: dict[str, object]
    ) -> None:
        from unraid_api.models import PluginInstallOperation

        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities(
            {"UnraidPluginsMutations": frozenset({field})}
        )
        op = {"id": "install:one", "status": "PENDING"}
        with patch.object(
            client,
            "mutate",
            new_callable=AsyncMock,
            return_value={"unraidPlugins": {field: op}},
        ) as mutate:
            result = await getattr(client, method)(
                "https://example.test/plugin.plg", **options
            )
            assert isinstance(result, PluginInstallOperation)
            assert result.id == "install:one"
            assert f"{field}(input: $input)" in mutate.call_args.args[0]
            assert "https://example.test" not in mutate.call_args.args[0]
            assert mutate.call_args.args[1] == {
                "input": {"url": "https://example.test/plugin.plg", **options}
            }

    @pytest.mark.parametrize("method", ["install_plugin", "install_language"])
    async def test_install_missing_capability(self, method: str) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities({})
        with patch.object(client, "mutate", new_callable=AsyncMock) as mutate:
            with pytest.raises(UnraidAPIError, match="Plugin installation"):
                await getattr(client, method)("https://example.test/plugin.plg")
            mutate.assert_not_called()

    @pytest.mark.parametrize("method", ["install_plugin", "install_language"])
    @pytest.mark.parametrize(
        "response",
        [
            {},
            {"unraidPlugins": None},
            {"unraidPlugins": {}},
            {"unraidPlugins": {"installPlugin": None, "installLanguage": None}},
        ],
    )
    async def test_install_missing_operation(
        self, method: str, response: dict[str, object]
    ) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities.permissive()
        with (
            patch.object(
                client, "mutate", new_callable=AsyncMock, return_value=response
            ),
            pytest.raises(UnraidAPIError, match="no operation"),
        ):
            await getattr(client, method)("https://example.test/plugin.plg")

    @pytest.mark.parametrize("has_uuid", [False, True])
    async def test_vm_uuid(self, has_uuid: bool) -> None:
        client = UnraidClient("unraid.test", "test-key")
        client._capabilities = ServerCapabilities(
            {"VmDomain": frozenset({"uuid"}) if has_uuid else frozenset()}
        )
        vm = {"id": "vm:one", "name": "Example", "state": "RUNNING"}
        if has_uuid:
            vm["uuid"] = "example-uuid"
        with patch.object(
            client,
            "query",
            new_callable=AsyncMock,
            return_value={"vms": {"domains": [vm]}},
        ) as query:
            result = await client.typed_get_vms()
            assert ("uuid" in query.call_args.args[0]) is has_uuid
            assert result[0].uuid == ("example-uuid" if has_uuid else None)


class TestEncryptedArrayTransport:
    """Decryption values never leave the client over a plaintext connection."""

    @pytest.mark.parametrize(
        "destination",
        [
            "http://unraid.test/graphql",
            "https://other.myunraid.net/graphql",
            "https://unraid.test:444/graphql",
        ],
    )
    @pytest.mark.parametrize(
        "credentials",
        [
            {"decryption_password": "example-password"},  # pragma: allowlist secret
            {"decryption_keyfile": "ZXhhbXBsZQ=="},
        ],
    )
    async def test_cached_unsafe_destination_is_ignored(
        self, destination: str, credentials: dict[str, str]
    ) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.post(
                "https://unraid.test/graphql",
                payload={"data": {"array": {"setState": {"state": "STARTED"}}}},
            )
            async with UnraidClient("unraid.test", "test-key") as client:
                client._resolved_url = destination
                with (
                    patch.object(
                        client,
                        "_discover_redirect_url",
                        side_effect=AssertionError("Discovery must not run"),
                    ),
                    patch.object(
                        client.session, "post", wraps=client.session.post
                    ) as post,
                ):
                    await client.start_array(**credentials)
                assert post.call_count == 1
                assert post.call_args.args[0] == "https://unraid.test/graphql"
                assert client._resolved_url == destination

    @pytest.mark.parametrize(
        "redirect", ["http://unraid.test/graphql", "http://tower.myunraid.net/graphql"]
    )
    async def test_post_downgrade_rejected(self, redirect: str) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.post(
                "https://unraid.test/graphql",
                status=307,
                headers={"Location": redirect},
            )
            async with UnraidClient("unraid.test", "test-key") as client:
                client._resolved_url = "https://unraid.test/graphql"
                with (
                    patch.object(
                        client.session, "post", wraps=client.session.post
                    ) as post,
                    pytest.raises(UnraidSSLError, match="requires an HTTPS"),
                ):
                    await client.start_array(
                        # pragma: allowlist nextline secret
                        **{"decryption_password": "example-password"}
                    )
                assert post.call_count == 1
                assert client._resolved_url == "https://unraid.test/graphql"

    @pytest.mark.parametrize("redirect", [False, True])
    async def test_https_credentials_in_variables_only(self, redirect: bool) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            final_url = (
                "https://unraid.test/redirect/graphql"
                if redirect
                else "https://unraid.test/graphql"
            )
            if redirect:
                m.post(
                    "https://unraid.test/graphql",
                    status=307,
                    headers={"Location": final_url},
                )
            m.post(
                final_url,
                payload={"data": {"array": {"setState": {"state": "STARTED"}}}},
            )
            async with UnraidClient("unraid.test", "test-key") as client:
                client._resolved_url = "https://unraid.test/graphql"
                with patch.object(
                    client.session, "post", wraps=client.session.post
                ) as post:
                    result = await client.start_array(
                        # pragma: allowlist nextline secret
                        **{"decryption_password": "example-password"}
                    )
                assert result["array"]["setState"]["state"] == "STARTED"
                assert post.call_count == (2 if redirect else 1)
                for call in post.call_args_list:
                    assert call.args[0].startswith("https://")
                    assert "example-password" not in call.kwargs["json"]["query"]
                    assert (
                        call.kwargs["json"]["variables"]["input"]["decryptionPassword"]
                        == "example-password"
                    )

    async def test_encrypted_start_bypasses_http_discovery(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.get(
                "http://unraid.test/graphql",
                status=302,
                headers={"Location": "https://unraid.test/graphql"},
            )
            m.post(
                "https://unraid.test/graphql",
                payload={"data": {"array": {"setState": {"state": "STARTED"}}}},
            )
            async with UnraidClient("unraid.test", "test-key") as client:
                with patch.object(
                    client,
                    "_discover_redirect_url",
                    side_effect=AssertionError("HTTP discovery must not run"),
                ):
                    result = await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
                assert result["array"]["setState"]["state"] == "STARTED"

    async def test_plain_array_start_allows_http(self) -> None:
        async with aiointercept(mock_external_urls=True) as m:
            m.post(
                "http://unraid.test/graphql",
                payload={"data": {"array": {"setState": {"state": "STARTED"}}}},
            )
            async with UnraidClient("unraid.test", "test-key") as client:
                client._resolved_url = "http://unraid.test/graphql"
                result = await client.start_array()
                assert result["array"]["setState"]["state"] == "STARTED"


async def test_vm_uuid_omitted_with_permissive_capabilities() -> None:
    """Unknown schemas retain the basic VM query that works on older servers."""
    client = UnraidClient("unraid.test", "test-key")
    client._capabilities = ServerCapabilities.permissive()
    with patch.object(
        client,
        "query",
        new_callable=AsyncMock,
        return_value={"vms": {"domains": [{"id": "vm:one", "name": "Example"}]}},
    ) as query:
        vms = await client.typed_get_vms()
        assert "uuid" not in query.call_args.args[0]
        assert vms[0].uuid is None


async def test_array_decryption_rejects_unverified_tls() -> None:
    """Disabling certificate checks cannot expose array unlock material."""
    async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
        client._resolved_url = "https://unraid.test/graphql"
        with (
            patch.object(client.session, "post") as post,
            pytest.raises(UnraidSSLError, match="certificate verification"),
        ):
            await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
        post.assert_not_called()


async def test_array_decryption_overrides_unverified_injected_session() -> None:
    """A verified per-request context overrides even an insecure shared connector."""
    import ssl

    connector = aiohttp.TCPConnector(ssl=False)
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        aiointercept(mock_external_urls=True) as m,
    ):
        m.post(
            "https://unraid.test/graphql",
            status=307,
            headers={"Location": "https://unraid.test/redirect/graphql"},
        )
        m.post(
            "https://unraid.test/redirect/graphql",
            payload={"data": {"array": {"setState": {"state": "STARTED"}}}},
        )
        async with UnraidClient("unraid.test", "test-key", session=session) as client:
            client._resolved_url = "https://unraid.test/graphql"
            with patch.object(session, "post", wraps=session.post) as post:
                await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
            assert post.call_count == 2
            contexts = [call.kwargs["ssl"] for call in post.call_args_list]
            assert contexts[0] is contexts[1]
            assert contexts[0].verify_mode == ssl.CERT_REQUIRED
            assert contexts[0].check_hostname is True


@pytest.mark.parametrize(
    "redirect",
    ["https://other.myunraid.net/graphql", "https://unraid.test:444/graphql"],
)
async def test_array_decryption_rejects_redirect_to_another_server(
    redirect: str,
) -> None:
    """A valid certificate for another endpoint does not authorize receiving secrets."""
    async with aiointercept(mock_external_urls=True) as m:
        m.post(
            "https://unraid.test/graphql", status=307, headers={"Location": redirect}
        )
        async with UnraidClient("unraid.test", "test-key") as client:
            client._resolved_url = "https://unraid.test/graphql"
            with (
                patch.object(client.session, "post", wraps=client.session.post) as post,
                pytest.raises(UnraidSSLError, match="configured server and port"),
            ):
                await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
            assert post.call_count == 1


@pytest.mark.parametrize(
    ("host", "https_port", "url"),
    [
        ("unraid.test", 8443, "https://unraid.test:8443/graphql"),
        ("https://unraid.test:8443", 443, "https://unraid.test:8443/graphql"),
        ("[::1]", 443, "https://[::1]/graphql"),
    ],
)
async def test_array_decryption_accepts_configured_https_port(
    host: str, https_port: int, url: str
) -> None:
    """Port and IPv6 configuration bind to the expected TLS endpoint."""
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"data": {"array": {"setState": {"state": "STARTED"}}}}
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    async with UnraidClient(host, "test-key", https_port=https_port) as client:
        with (
            patch.object(client.session, "post", return_value=context) as post,
            patch.object(
                client,
                "_discover_redirect_url",
                side_effect=AssertionError("HTTP discovery must not run"),
            ),
        ):
            result = await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
            assert result["array"]["setState"]["state"] == "STARTED"
            assert post.call_args.args[0] == url


async def test_failed_encrypted_start_does_not_poison_plain_request_url() -> None:
    """An HTTP-only server still works for ordinary requests after an unlock fails."""
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value={"data": {"online": True}})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    async with UnraidClient("unraid.test", "test-key") as client:
        with (
            patch.object(
                client.session,
                "post",
                side_effect=[aiohttp.ClientConnectionError(), context],
            ) as post,
            patch.object(
                client,
                "_discover_redirect_url",
                new_callable=AsyncMock,
                return_value=(None, False),
            ) as discover,
        ):
            with pytest.raises(UnraidConnectionError):
                await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
            assert client._resolved_url is None
            discover.assert_not_called()
            assert await client.query("query { online }") == {"online": True}
            discover.assert_awaited_once()
            assert post.call_args.args[0] == "http://unraid.test/graphql"
            assert client._resolved_url == "http://unraid.test/graphql"


async def test_encrypted_start_rejects_invalid_configured_hostname() -> None:
    """Malformed authority input fails before posting any unlock values."""
    async with UnraidClient("?", "test-key") as client:
        with (
            patch.object(client.session, "post") as post,
            pytest.raises(UnraidConnectionError, match="Invalid configured HTTPS"),
        ):
            await client.start_array(decryption_keyfile="ZXhhbXBsZQ==")
        post.assert_not_called()


async def test_ordinary_query_still_caches_post_redirect_destination() -> None:
    """Unlock isolation leaves ordinary redirect discovery and caching unchanged."""
    redirect = MagicMock()
    redirect.status = 307
    redirect.headers = {"Location": "https://unraid.test/graphql"}
    response = MagicMock()
    response.json = AsyncMock(return_value={"data": {"online": True}})
    first = MagicMock()
    first.__aenter__ = AsyncMock(return_value=redirect)
    second = MagicMock()
    second.__aenter__ = AsyncMock(return_value=response)
    async with UnraidClient("unraid.test", "test-key") as client:
        client._resolved_url = "http://unraid.test/graphql"
        with patch.object(client.session, "post", side_effect=[first, second]) as post:
            assert await client.query("query { online }") == {"online": True}
        assert client._resolved_url == "https://unraid.test/graphql"
        assert [call.args[0] for call in post.call_args_list] == [
            "http://unraid.test/graphql",
            "https://unraid.test/graphql",
        ]
