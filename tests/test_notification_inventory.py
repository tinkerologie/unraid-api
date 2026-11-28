"""Contract tests for the typed notification inventory."""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from unraid_api import Notification, UnraidAPIError, UnraidClient


async def test_typed_inventory_uses_the_legacy_query_and_normalizes_items() -> None:
    client = UnraidClient("unraid.test", "test-key")
    payload = {
        "overview": {"archive": {"total": 1}},
        "list": [
            {"id": "old", "timestamp": "2026-11-01T12:00:00Z", "type": "ARCHIVE"},
            {"title": "Missing ID"},
        ],
    }
    query = AsyncMock(return_value={"notifications": payload})
    client.query = query  # type: ignore[method-assign]

    assert await client.get_notifications("ARCHIVE", 5, 10) == payload
    legacy_call = query.call_args
    query.reset_mock()
    items = await client.typed_get_notifications("ARCHIVE", 5, 10)

    query.assert_awaited_once_with(*legacy_call.args, **legacy_call.kwargs)
    assert legacy_call.args[1] == {"type": "ARCHIVE", "limit": 5, "offset": 10}
    assert items == [
        Notification(
            id="old",
            timestamp=datetime(2026, 11, 1, 12, tzinfo=UTC),
            type="ARCHIVE",
        )
    ]


@pytest.mark.parametrize("value", [None, {}, {"list": None}, {"list": "invalid"}])
async def test_invalid_page_raises_library_error(value: object) -> None:
    client = UnraidClient("unraid.test", "test-key")
    client.query = AsyncMock(return_value={"notifications": value})  # type: ignore[method-assign]

    with pytest.raises(UnraidAPIError, match="notification inventory"):
        await client.typed_get_notifications()


async def test_empty_page_is_successful() -> None:
    client = UnraidClient("unraid.test", "test-key")
    client.query = AsyncMock(return_value={"notifications": {"list": []}})  # type: ignore[method-assign]

    assert await client.typed_get_notifications() == []


async def test_typed_get_notifications_avoids_runtime_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = UnraidClient("unraid.test", "test-key")
    payload = {
        "overview": {"archive": {"total": 1}},
        "list": [
            {"id": "old", "timestamp": "2026-11-01T12:00:00Z", "type": "ARCHIVE"},
            {"title": "Missing ID"},
        ],
    }
    client.query = AsyncMock(return_value={"notifications": payload})  # type: ignore[method-assign]

    original_import = builtins.__import__
    recorded: list[tuple[str, tuple[str, ...]]] = []

    def guarded_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if (
            isinstance(globals, Mapping)
            and globals.get("__name__") == "unraid_api.client"
            and (
                (name == "pydantic" and "ValidationError" in fromlist)
                or name == "unraid_api.models"
            )
        ):
            recorded.append((name, tuple(fromlist)))
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    items = await client.typed_get_notifications("ARCHIVE", 5, 10)

    assert recorded == []
    assert items == [
        Notification(
            id="old",
            timestamp=datetime(2026, 11, 1, 12, tzinfo=UTC),
            type="ARCHIVE",
        )
    ]
