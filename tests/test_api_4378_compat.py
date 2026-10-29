"""Unraid API 4.37.8+ compatibility (#135).

4.37.8 made the ``docker`` and ``vms`` query roots nullable (unraid/api#2123)
and refuses schema introspection unless the developer sandbox is enabled
(unraid/api#2095, #2129).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiointercept import aiointercept

from unraid_api import UnraidClient
from unraid_api.capabilities import RETIRED_FIELDS, ServerCapabilities
from unraid_api.exceptions import UnraidAPIError

INTROSPECTION_DISABLED = {
    "errors": [
        {
            "message": "GraphQL introspection is not allowed, but the current "
            "request is for introspection.",
            "extensions": {"code": "INTROSPECTION_DISABLED"},
        }
    ]
}


def _client(response: dict[str, Any]) -> tuple[UnraidClient, AsyncMock]:
    client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
    client._capabilities = ServerCapabilities.introspection_disabled()
    request = AsyncMock(return_value=response)
    client._make_request = request  # type: ignore[method-assign]
    return client, request


def _null_root(root: str, message: str = "Service is not running") -> dict[str, Any]:
    return {"data": {root: None}, "errors": [{"message": message, "path": [root]}]}


# --------------------------------------------------------------------------
# Nullable docker / vms roots
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "args", "root"),
    [
        ("typed_get_containers", (), "docker"),
        ("typed_get_containers_safe", (), "docker"),
        ("get_containers", (), "docker"),
        ("get_container_update_statuses", (), "docker"),
        ("get_docker_port_conflicts", (), "docker"),
        ("get_docker_networks", (), "docker"),
        ("get_container_logs", ("abc",), "docker"),
        ("get_docker_organizer", (), "docker"),
        ("typed_get_vms", (), "vms"),
        ("get_vms", (), "vms"),
    ],
)
async def test_null_service_root_raises_api_error(
    method: str, args: tuple[Any, ...], root: str
) -> None:
    """A failed service is an UnraidAPIError, never AttributeError or []."""
    client, _ = _client(_null_root(root, f"{root} is not running"))
    with pytest.raises(UnraidAPIError) as exc_info:
        await getattr(client, method)(*args)
    assert exc_info.value.errors[0]["path"] == [root]
    assert f"{root} is not running" in str(exc_info.value)


async def test_partial_result_with_one_healthy_root_is_returned() -> None:
    """Healthy roots still come back when another root failed."""
    client, _ = _client(
        {
            "data": {"docker": None, "online": True},
            "errors": [{"message": "Docker is not running", "path": ["docker"]}],
        }
    )
    assert await client.query("query { docker { id } online }") == {
        "docker": None,
        "online": True,
    }


async def test_null_root_without_errors_is_returned() -> None:
    """A root that is legitimately null without errors is data, not failure."""
    client, _ = _client({"data": {"customization": None}})
    assert await client.query("query { customization { theme { name } } }") == {
        "customization": None
    }


# --------------------------------------------------------------------------
# GraphQL errors on HTTP 4xx
# --------------------------------------------------------------------------


async def test_rejected_request_keeps_graphql_errors() -> None:
    """The INTROSPECTION_DISABLED code survives the HTTP 400."""
    async with aiointercept(mock_external_urls=True) as m:
        m.get("http://unraid.test/graphql", status=400)
        m.post("http://unraid.test/graphql", status=400, payload=INTROSPECTION_DISABLED)
        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            with pytest.raises(UnraidAPIError) as exc_info:
                await client.query('{ __type(name: "VmDomain") { name } }')
    assert exc_info.value.message == "GraphQL request rejected (HTTP 400)"
    assert exc_info.value.errors[0]["extensions"]["code"] == "INTROSPECTION_DISABLED"


async def test_rejected_request_after_redirect_keeps_graphql_errors() -> None:
    """Servers that redirect the POST (SSL modes) keep the code too."""
    async with aiointercept(mock_external_urls=True) as m:
        m.get("http://unraid.test/graphql", status=400)
        m.post(
            "http://unraid.test/graphql",
            status=302,
            headers={"Location": "https://unraid.test/graphql"},
        )
        m.post(
            "https://unraid.test/graphql", status=400, payload=INTROSPECTION_DISABLED
        )
        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            caps = await client.get_capabilities()
    assert not caps.is_permissive
    assert caps.has("VmDomain.uuid")


@pytest.mark.parametrize(
    "body",
    ["not json", '{"message": "no errors key"}', '{"errors": []}', "[1, 2]"],
)
async def test_rejected_request_without_graphql_errors_keeps_http_error(
    body: str,
) -> None:
    async with aiointercept(mock_external_urls=True) as m:
        m.get("http://unraid.test/graphql", status=400)
        m.post("http://unraid.test/graphql", status=400, body=body)
        async with UnraidClient("unraid.test", "test-key", verify_ssl=False) as client:
            with pytest.raises(UnraidAPIError, match="HTTP error 400"):
                await client.query("query { online }")


# --------------------------------------------------------------------------
# Capabilities when introspection is disabled
# --------------------------------------------------------------------------


async def test_introspection_disabled_gives_current_capabilities() -> None:
    client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
    client._make_request = AsyncMock(  # type: ignore[method-assign]
        side_effect=UnraidAPIError(
            "GraphQL request rejected (HTTP 400)",
            errors=INTROSPECTION_DISABLED["errors"],
        )
    )
    caps = await client.get_capabilities()
    assert not caps.is_permissive
    assert caps.has("VmDomain.uuid")
    assert caps.has("DockerMutations.restart")
    assert not caps.has("ArrayMutations.removeDiskFromArray")
    assert await client.get_capabilities() is caps  # cached


async def test_other_introspection_failures_stay_permissive() -> None:
    client = UnraidClient("unraid.test", "test-key", verify_ssl=False)
    client._make_request = AsyncMock(  # type: ignore[method-assign]
        side_effect=UnraidAPIError("HTTP error 400: Bad Request")
    )
    caps = await client.get_capabilities()
    assert caps.is_permissive
    assert caps.has("ArrayMutations.removeDiskFromArray")


async def test_vm_uuid_is_requested_when_introspection_is_disabled() -> None:
    """The regression: permissive capabilities dropped VM UUIDs."""
    client, request = _client(
        {"data": {"vms": {"domains": [{"id": "1", "name": "HA", "state": "RUNNING"}]}}}
    )
    await client.typed_get_vms()
    assert "uuid" in request.call_args.args[0]["query"]


async def test_retired_disk_removal_is_refused_without_a_request() -> None:
    client, request = _client({"data": {}})
    with (
        pytest.warns(DeprecationWarning),
        pytest.raises(UnraidAPIError, match="no longer supports direct array disk"),
    ):
        await client.remove_array_disk("disk1")
    request.assert_not_called()


def test_introspection_disabled_capabilities() -> None:
    caps = ServerCapabilities.introspection_disabled()
    assert not caps.is_permissive
    assert caps.has("Query.anything")
    assert caps.has_all("Query.docker", "Mutation.notifyIfUnique")
    assert not any(caps.has(path) for path in RETIRED_FIELDS)
    with pytest.raises(ValueError, match="dotted"):
        ServerCapabilities.from_introspection_response({}).has("nodot")
