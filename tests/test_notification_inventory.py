"""Contract tests for the typed notification inventory."""

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
