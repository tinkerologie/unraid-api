"""Mutations validate against the pinned upstream Unraid API schema (#138).

Each case runs a client method with ``mutate`` captured, then checks the
document with ``graphql.validate`` and coerces the variables against the
operation's variable definitions, so wrong input type names, nullability and
unknown input fields fail here instead of on a server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from graphql import (
    GraphQLSchema,
    OperationDefinitionNode,
    build_schema,
    parse,
    validate,
)
from graphql.execution.values import get_variable_values

from unraid_api import UnraidClient

SCHEMA_FILE = Path(__file__).parent / "fixtures" / "unraid-api-v4.37.9.graphql"
API_KEY_ID = "4c2b5a4d0f6e4f5aa1b2c3d4e5f60718:key-1"


@pytest.fixture(scope="session")
def schema() -> GraphQLSchema:
    """The pinned upstream schema."""
    return build_schema(SCHEMA_FILE.read_text(encoding="utf-8"))


ORGANIZER = {
    "moveDockerEntriesToFolder": {"version": 1, "views": []},
}
SERVER = {
    "updateServerIdentity": {
        "id": "server",
        "name": "Tower",
        "comment": None,
        "guid": "g",
        "lanip": "192.168.1.2",
        "wanip": "",
        "localurl": "http://tower",
        "remoteurl": "",
        "status": "ONLINE",
        "apikey": "",
    }
}

CASES: list[tuple[str, tuple[Any, ...], dict[str, Any], dict[str, Any]]] = [
    ("create_api_key", ("ha",), {}, {"apiKey": {"create": {"id": "1"}}}),
    (
        "create_api_key",
        ("ha",),
        {"description": "Home Assistant", "roles": ["ADMIN", "VIEWER"]},
        {"apiKey": {"create": {"id": "1"}}},
    ),
    ("update_api_key", (API_KEY_ID,), {}, {"apiKey": {"update": {"id": "1"}}}),
    (
        "update_api_key",
        (API_KEY_ID,),
        {"name": "ha", "description": "Home Assistant"},
        {"apiKey": {"update": {"id": "1"}}},
    ),
    ("delete_api_keys", ([API_KEY_ID],), {}, {"apiKey": {"delete": True}}),
    ("move_docker_entries_to_folder", (["c1", "c2"],), {}, ORGANIZER),
    ("move_docker_entries_to_folder", (["c1"], None), {}, ORGANIZER),
    ("move_docker_entries_to_folder", (["c1"], "folder-1"), {}, ORGANIZER),
    ("update_server_identity", ("Tower",), {}, SERVER),
    (
        "update_server_identity",
        ("Tower",),
        {"comment": "Media server", "sys_model": "Custom"},
        SERVER,
    ),
]


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "response"),
    CASES,
    ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)],
)
async def test_mutation_matches_upstream_schema(
    schema: GraphQLSchema,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    response: dict[str, Any],
) -> None:
    client = UnraidClient("unraid.test", "test-key")
    mutate = AsyncMock(return_value=response)
    client.mutate = mutate  # type: ignore[method-assign]

    await getattr(client, method)(*args, **kwargs)

    document_text, variables = mutate.call_args.args
    document = parse(document_text)
    assert validate(schema, document) == []
    operation = next(
        d for d in document.definitions if isinstance(d, OperationDefinitionNode)
    )
    coerced = get_variable_values(
        schema, operation.variable_definitions or (), variables or {}
    )
    # A list means coercion errors; success is a dict (graphql-core 3.2) or a
    # VariableValues object (3.3).
    assert not isinstance(coerced, list), [str(error) for error in coerced]


async def test_update_server_identity_sends_only_given_fields() -> None:
    client = UnraidClient("unraid.test", "test-key")
    client.mutate = AsyncMock(return_value=SERVER)  # type: ignore[method-assign]
    await client.update_server_identity("Tower")
    assert client.mutate.call_args.args[1] == {"name": "Tower"}


@pytest.mark.parametrize("name", ["", "   "])
async def test_update_server_identity_rejects_blank_name(name: str) -> None:
    client = UnraidClient("unraid.test", "test-key")
    client.mutate = AsyncMock()  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="name must not be blank"):
        await client.update_server_identity(name)
    client.mutate.assert_not_called()


@pytest.mark.parametrize(
    ("args", "destination"),
    [((["c1"],), "root"), ((["c1"], None), "root"), ((["c1"], "folder-1"), "folder-1")],
)
async def test_move_docker_entries_destination(
    args: tuple[Any, ...], destination: str
) -> None:
    """None (or omitted) moves to Unraid's default organizer root folder."""
    client = UnraidClient("unraid.test", "test-key")
    client.mutate = AsyncMock(return_value=ORGANIZER)  # type: ignore[method-assign]
    await client.move_docker_entries_to_folder(*args)
    assert client.mutate.call_args.args[1] == {
        "sourceEntryIds": ["c1"],
        "destinationFolderId": destination,
    }


@pytest.mark.parametrize("destination", ["", "  "])
async def test_move_docker_entries_rejects_blank_destination(destination: str) -> None:
    client = UnraidClient("unraid.test", "test-key")
    client.mutate = AsyncMock()  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="destination_folder_id must not be blank"):
        await client.move_docker_entries_to_folder(["c1"], destination)
    client.mutate.assert_not_called()


async def test_api_key_variables_are_unchanged() -> None:
    """Only the input type names changed; the sent fields stay the same."""
    client = UnraidClient("unraid.test", "test-key")
    client.mutate = AsyncMock(  # type: ignore[method-assign]
        return_value={"apiKey": {"create": {}, "update": {}, "delete": True}}
    )
    await client.create_api_key("ha", description="d", roles=["ADMIN"])
    assert client.mutate.call_args.args[1] == {
        "input": {"name": "ha", "description": "d", "roles": ["ADMIN"]}
    }
    await client.update_api_key(API_KEY_ID, name="n")
    assert client.mutate.call_args.args[1] == {"input": {"id": API_KEY_ID, "name": "n"}}
    result = await client.delete_api_keys([API_KEY_ID])
    assert client.mutate.call_args.args[1] == {"input": {"ids": [API_KEY_ID]}}
    assert result == {"apiKey": {"create": {}, "update": {}, "delete": True}}
