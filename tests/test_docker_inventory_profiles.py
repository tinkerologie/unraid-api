"""Verify capability edge cases through the typed Docker inventory readers."""

from unittest.mock import AsyncMock, patch

from unraid_api import UnraidClient
from unraid_api.capabilities import ServerCapabilities


async def test_older_tailscale_schema_keeps_minimal_full_selection() -> None:
    """A server can expose Tailscale status without introspecting its fields."""
    client = UnraidClient("unraid.test", "test-key")
    caps = ServerCapabilities({"DockerContainer": frozenset({"tailscaleStatus"})})
    with (
        patch.object(client, "get_capabilities", AsyncMock(return_value=caps)),
        patch.object(
            client, "query", AsyncMock(return_value={"docker": {"containers": []}})
        ) as query,
    ):
        assert await client.typed_get_containers() == []
        assert "tailscaleStatus { online }" in query.call_args.args[0]
        assert await client.typed_get_containers_safe() == []
        assert "tailscaleStatus" not in query.call_args.args[0]
