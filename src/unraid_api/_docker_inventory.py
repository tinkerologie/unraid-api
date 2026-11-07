"""Query and decode the full and polling profiles of Docker inventory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from unraid_api.models import DockerContainer

if TYPE_CHECKING:
    from unraid_api.capabilities import ServerCapabilities

_CORE_FIELDS = ("id", "names", "image", "imageId", "state", "status", "autoStart")
_POLL_FIELDS = (
    "autoStartOrder",
    "isUpdateAvailable",
    "iconUrl",
    "webUiUrl",
    "projectUrl",
    "registryUrl",
    "supportUrl",
    "tailscaleEnabled",
)
_FULL_ONLY_FIELDS = (
    "isOrphaned",
    "command",
    "created",
    "sizeRootFs",
    "sizeRw",
    "sizeLog",
    "autoStartWait",
    "shell",
    "templatePath",
    "isRebuildReady",
    "lanIpPorts",
    "labels",
    "networkSettings",
    "mounts",
)


def build_container_query(caps: ServerCapabilities, *, polling: bool) -> str:
    """Render the capability-aware query for the selected inventory profile."""
    fields = _POLL_FIELDS if polling else (*_POLL_FIELDS, *_FULL_ONLY_FIELDS)
    fragments = [
        *_CORE_FIELDS,
        *(field for field in fields if caps.has(f"DockerContainer.{field}")),
    ]
    if not polling:
        fragments.extend(_full_selections(caps))
    body = "\n".join(fragments)
    return f"""query {{
        docker {{
            containers {{
                {body}
            }}
        }}
    }}"""


def _full_selections(caps: ServerCapabilities) -> list[str]:
    """Include supported nested selections only for the full inventory."""

    def has(field: str) -> bool:
        return caps.has(f"DockerContainer.{field}")

    def ts_has(field: str) -> bool:
        return caps.has(f"TailscaleStatus.{field}")

    fragments: list[str] = []
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

    return fragments


def decode_containers(result: dict[str, Any]) -> list[DockerContainer]:
    """Decode the inventory returned by either typed profile."""
    containers = (result.get("docker") or {}).get("containers") or []
    return [DockerContainer.from_api_response(container) for container in containers]
