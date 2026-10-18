"""Tests for WebSocket GraphQL subscription support."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from unraid_api import UnraidClient
from unraid_api.exceptions import (
    UnraidAPIError,
    UnraidAuthenticationError,
    UnraidConnectionError,
    UnraidSSLError,
    UnraidTimeoutError,
)

# ============================================================================
# Helpers
# ============================================================================


def _ws_text_msg(data: dict[str, Any]) -> MagicMock:
    """Create a mock WSMessage with TEXT type."""
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = json.dumps(data)
    return msg


def _ws_close_msg() -> MagicMock:
    """Create a mock WSMessage with CLOSE type."""
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.CLOSE
    msg.data = None
    return msg


def _ws_error_msg() -> MagicMock:
    """Create a mock WSMessage with ERROR type."""
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.ERROR
    msg.data = None
    return msg


class MockWebSocket:
    """Mock WebSocket that replays a list of messages."""

    def __init__(self, messages: list[MagicMock | BaseException]) -> None:
        self._messages = messages
        self._send_history: list[str] = []
        self.closed = False
        self._receive_index = 0

    async def send_str(self, data: str) -> None:
        self._send_history.append(data)

    async def receive(self) -> MagicMock:
        if self._receive_index >= len(self._messages):
            return _ws_close_msg()
        msg = self._messages[self._receive_index]
        self._receive_index += 1
        if isinstance(msg, BaseException):
            raise msg
        return msg

    def __aiter__(self) -> MockWebSocket:
        return self

    async def __anext__(self) -> MagicMock:
        if self._receive_index >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._receive_index]
        self._receive_index += 1
        assert isinstance(msg, MagicMock)
        return msg

    async def close(self) -> None:
        self.closed = True

    def exception(self) -> Exception | None:
        return None


# ============================================================================
# _get_ws_url Tests
# ============================================================================


class TestGetWsUrl:
    """Tests for WebSocket URL derivation."""

    def test_https_to_wss(self, host: str, api_key: str) -> None:
        """Test https URL converts to wss."""
        client = UnraidClient(host, api_key)
        client._resolved_url = "https://192.168.1.100/graphql"
        assert client._get_ws_url() == "wss://192.168.1.100/graphql"

    def test_http_to_ws(self, host: str, api_key: str) -> None:
        """Test http URL converts to ws."""
        client = UnraidClient(host, api_key)
        client._resolved_url = "http://192.168.1.100/graphql"
        assert client._get_ws_url() == "ws://192.168.1.100/graphql"

    def test_myunraid_net_to_wss(self, host: str, api_key: str) -> None:
        """Test myunraid.net URL converts to wss."""
        client = UnraidClient(host, api_key)
        client._resolved_url = "https://192-168-1-100.abc123.myunraid.net/graphql"
        assert client._get_ws_url() == "wss://192-168-1-100.abc123.myunraid.net/graphql"

    def test_custom_port_preserved(self, host: str, api_key: str) -> None:
        """Test custom port is preserved in WS URL."""
        client = UnraidClient(host, api_key)
        client._resolved_url = "https://192.168.1.100:8443/graphql"
        assert client._get_ws_url() == "wss://192.168.1.100:8443/graphql"

    def test_raises_without_resolved_url(self, host: str, api_key: str) -> None:
        """Test raises when URL not resolved."""
        client = UnraidClient(host, api_key)
        with pytest.raises(UnraidConnectionError, match="not resolved"):
            client._get_ws_url()


# ============================================================================
# subscribe() Protocol Tests
# ============================================================================


class TestSubscribeProtocol:
    """Tests for the subscribe() graphql-transport-ws protocol."""

    @pytest.fixture
    def ws_client(self, host: str, api_key: str) -> UnraidClient:
        """Create a client with pre-resolved URL and mock session."""
        from unraid_api.capabilities import ServerCapabilities

        session = MagicMock()
        client = UnraidClient(host, api_key, session=session)
        client._resolved_url = f"https://{host}/graphql"
        client._capabilities = ServerCapabilities.permissive()
        return client

    async def test_subscribe_yields_next_payloads(
        self, ws_client: UnraidClient
    ) -> None:
        """Test that subscribe yields data from 'next' messages."""
        ack = _ws_text_msg({"type": "connection_ack"})
        next1 = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {"data": {"dockerContainerStats": {"cpuPercent": 15.0}}},
            }
        )
        next2 = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {"data": {"dockerContainerStats": {"cpuPercent": 20.0}}},
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next1, next2, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[dict[str, Any]] = []
        async for data in ws_client.subscribe(
            "subscription { dockerContainerStats { cpuPercent } }"
        ):
            results.append(data)

        assert len(results) == 2
        assert results[0]["dockerContainerStats"]["cpuPercent"] == 15.0
        assert results[1]["dockerContainerStats"]["cpuPercent"] == 20.0

    async def test_subscribe_sends_correct_protocol_messages(
        self, ws_client: UnraidClient
    ) -> None:
        """Test that subscribe sends init, subscribe, and complete messages."""
        ack = _ws_text_msg({"type": "connection_ack"})
        complete = _ws_text_msg({"id": "test", "type": "complete"})
        ws = MockWebSocket([ack, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        async for _ in ws_client.subscribe("subscription { test }"):
            pass

        assert len(ws._send_history) >= 2
        init_msg = json.loads(ws._send_history[0])
        assert init_msg["type"] == "connection_init"
        assert "x-api-key" in init_msg["payload"]

        sub_msg = json.loads(ws._send_history[1])
        assert sub_msg["type"] == "subscribe"
        assert sub_msg["payload"]["query"] == "subscription { test }"

    async def test_subscribe_with_variables(self, ws_client: UnraidClient) -> None:
        """Test that variables are passed in subscribe payload."""
        ack = _ws_text_msg({"type": "connection_ack"})
        complete = _ws_text_msg({"id": "test", "type": "complete"})
        ws = MockWebSocket([ack, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        async for _ in ws_client.subscribe(
            "subscription LogFile($path: String!) { logFile(path: $path) { content } }",
            variables={"path": "/var/log/syslog"},
        ):
            pass

        sub_msg = json.loads(ws._send_history[1])
        assert sub_msg["payload"]["variables"] == {"path": "/var/log/syslog"}

    async def test_subscribe_handles_close_message(
        self, ws_client: UnraidClient
    ) -> None:
        """Test that subscribe exits on CLOSE message."""
        ack = _ws_text_msg({"type": "connection_ack"})
        close = _ws_close_msg()
        ws = MockWebSocket([ack, close])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[dict[str, Any]] = []
        async for data in ws_client.subscribe("subscription { test }"):
            results.append(data)

        assert results == []

    async def test_subscribe_handles_error_message(
        self, ws_client: UnraidClient
    ) -> None:
        """Test that subscribe raises on 'error' type message."""
        ack = _ws_text_msg({"type": "connection_ack"})
        error = _ws_text_msg(
            {
                "id": "test",
                "type": "error",
                "payload": [{"message": "Something went wrong"}],
            }
        )
        ws = MockWebSocket([ack, error])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidAPIError, match="Something went wrong"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass

    async def test_subscribe_handles_ws_error_type(
        self, ws_client: UnraidClient
    ) -> None:
        """Test that subscribe raises on WebSocket ERROR message type."""
        ack = _ws_text_msg({"type": "connection_ack"})
        error = _ws_error_msg()
        ws = MockWebSocket([ack, error])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidConnectionError, match="WebSocket error"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass

    async def test_subscribe_handles_errors_in_next_payload(
        self, ws_client: UnraidClient
    ) -> None:
        """Test that subscribe raises on errors inside a next payload (no data)."""
        ack = _ws_text_msg({"type": "connection_ack"})
        next_err = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {"errors": [{"message": "Failed to validate session"}]},
            }
        )
        ws = MockWebSocket([ack, next_err])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidAPIError, match="Failed to validate session"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass


# ============================================================================
# subscribe() Connection Error Tests
# ============================================================================


class TestSubscribeErrors:
    """Tests for subscribe() error handling."""

    @pytest.fixture
    def ws_client(self, host: str, api_key: str) -> UnraidClient:
        """Create a client with pre-resolved URL and mock session."""
        from unraid_api.capabilities import ServerCapabilities

        session = MagicMock()
        client = UnraidClient(host, api_key, session=session)
        client._resolved_url = f"https://{host}/graphql"
        client._capabilities = ServerCapabilities.permissive()
        return client

    async def test_connection_timeout(self, ws_client: UnraidClient) -> None:
        """Test timeout during WebSocket connection."""
        ws_client._session.ws_connect = AsyncMock(  # type: ignore[union-attr]
            side_effect=TimeoutError("timed out")
        )
        with pytest.raises(UnraidTimeoutError, match="timed out"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass

    async def test_ssl_error(self, ws_client: UnraidClient) -> None:
        """Test SSL error during WebSocket connection."""

        # aiohttp.ClientSSLError has complex init; use a subclass for testing
        class _TestSSLError(aiohttp.ClientSSLError, Exception):
            def __init__(self) -> None:
                Exception.__init__(self, "cert failed")

        ws_client._session.ws_connect = AsyncMock(  # type: ignore[union-attr]
            side_effect=_TestSSLError()
        )
        with pytest.raises(UnraidSSLError, match="SSL certificate"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass

    async def test_client_error(self, ws_client: UnraidClient) -> None:
        """Test generic connection error during WebSocket connection."""
        ws_client._session.ws_connect = AsyncMock(  # type: ignore[union-attr]
            side_effect=aiohttp.ClientError("connection refused")
        )
        with pytest.raises(UnraidConnectionError, match="WebSocket connection failed"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass

    async def test_closed_during_handshake(self, ws_client: UnraidClient) -> None:
        """Test WebSocket closed during connection_init handshake."""
        close_msg = _ws_close_msg()
        ws = MockWebSocket([close_msg])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(
            UnraidConnectionError, match="closed during connection_init"
        ):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass
        assert ws.closed

    async def test_error_during_handshake(self, ws_client: UnraidClient) -> None:
        """Test WebSocket ERROR message during connection_init handshake."""
        ws = MockWebSocket([_ws_error_msg()])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidConnectionError, match="error during handshake"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass
        assert ws.closed

    async def test_connection_rejected(self, ws_client: UnraidClient) -> None:
        """Test server rejects connection with connection_error."""
        error_msg = _ws_text_msg(
            {"type": "connection_error", "payload": {"message": "Forbidden"}}
        )
        ws = MockWebSocket([error_msg])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidAuthenticationError, match="Connection rejected"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass
        assert ws.closed

    async def test_unexpected_ack_type(self, ws_client: UnraidClient) -> None:
        """Test unexpected message type instead of connection_ack."""
        unexpected = _ws_text_msg({"type": "ka"})
        ws = MockWebSocket([unexpected])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidConnectionError, match="Expected connection_ack"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass
        assert ws.closed

    async def test_ack_receive_timeout(self, ws_client: UnraidClient) -> None:
        """Test timeout while waiting for connection_ack."""
        ws = MockWebSocket([TimeoutError()])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidTimeoutError, match="connection_ack") as exc_info:
            async for _ in ws_client.subscribe("subscription { test }"):
                pass
        assert isinstance(exc_info.value.__cause__, TimeoutError)
        assert ws.closed

    async def test_handshake_close_error_keeps_original(
        self, ws_client: UnraidClient
    ) -> None:
        """Test a close failure after a failed handshake keeps the original error."""
        ws = MockWebSocket([TimeoutError()])
        ws.close = AsyncMock(side_effect=RuntimeError("close failed"))  # type: ignore[method-assign]
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        with pytest.raises(UnraidTimeoutError, match="connection_ack"):
            async for _ in ws_client.subscribe("subscription { test }"):
                pass
        ws.close.assert_awaited_once()

    async def test_idle_receive_timeout(self, ws_client: UnraidClient) -> None:
        """Test an idle subscription timeout raises UnraidTimeoutError and cleans up."""
        ack = _ws_text_msg({"type": "connection_ack"})
        next1 = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {"data": {"value": 1}},
            }
        )
        ws = MockWebSocket([ack, next1, TimeoutError()])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        gen = ws_client.subscribe("subscription { test }")
        assert await gen.__anext__() == {"value": 1}
        with pytest.raises(UnraidTimeoutError, match="300s") as exc_info:
            await gen.__anext__()
        assert isinstance(exc_info.value.__cause__, TimeoutError)

        assert ws.closed
        sent = [json.loads(m) for m in ws._send_history]
        sub_id = next(m["id"] for m in sent if m["type"] == "subscribe")
        assert {"id": sub_id, "type": "complete"} in sent

    async def test_cleanup_on_generator_break(self, ws_client: UnraidClient) -> None:
        """Test that WebSocket is cleaned up when consumer breaks early."""
        ack = _ws_text_msg({"type": "connection_ack"})
        next1 = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {"data": {"value": 1}},
            }
        )
        next2 = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {"data": {"value": 2}},
            }
        )
        ws = MockWebSocket([ack, next1, next2])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        gen = ws_client.subscribe("subscription { test }")
        data = await gen.__anext__()
        assert data == {"value": 1}
        await gen.aclose()

        assert ws.closed


# ============================================================================
# Typed Subscription Method Tests
# ============================================================================


class TestTypedSubscriptions:
    """Tests for typed subscribe_* convenience methods."""

    @pytest.fixture
    def ws_client(self, host: str, api_key: str) -> UnraidClient:
        """Create a client with pre-resolved URL and mock session."""
        from unraid_api.capabilities import ServerCapabilities

        session = MagicMock()
        client = UnraidClient(host, api_key, session=session)
        client._resolved_url = f"https://{host}/graphql"
        client._capabilities = ServerCapabilities.permissive()
        return client

    async def test_subscribe_container_stats(self, ws_client: UnraidClient) -> None:
        """Test subscribe_container_stats yields DockerContainerStats."""
        from unraid_api.models import DockerContainerStats

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "dockerContainerStats": {
                            "id": "container:abc",
                            "cpuPercent": 25.5,
                            "memUsage": "512MB / 2GB",
                            "memPercent": 25.0,
                            "netIO": "100MB / 50MB",
                            "blockIO": "10MB / 5MB",
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[DockerContainerStats] = []
        async for stats in ws_client.subscribe_container_stats():
            results.append(stats)

        assert len(results) == 1
        assert isinstance(results[0], DockerContainerStats)
        assert results[0].cpuPercent == 25.5
        assert results[0].memUsage == "512MB / 2GB"
        assert results[0].netIO == "100MB / 50MB"

    async def test_subscribe_container_stats_strips_ansi_from_id(
        self, ws_client: UnraidClient
    ) -> None:
        """The first row of each docker stats cycle glues clear-screen/
        cursor-home escapes onto the id; the yielded model must be clean (#71)."""
        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "dockerContainerStats": {
                            "id": "container:\x1b[J\x1b[H25d9c2630a90520ed9d9f6b2",
                            "cpuPercent": 1.0,
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results = []
        async for stats in ws_client.subscribe_container_stats():
            results.append(stats)

        assert results[0].id == "container:25d9c2630a90520ed9d9f6b2"
        assert "\x1b" not in (results[0].id or "")

    async def test_subscribe_cpu_metrics(self, ws_client: UnraidClient) -> None:
        """Test subscribe_cpu_metrics yields CpuMetrics."""
        from unraid_api.models import CpuMetrics

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "systemMetricsCpu": {
                            "percentTotal": 35.5,
                            "cpus": [
                                {"percentTotal": 40.0},
                                {"percentTotal": 31.0},
                            ],
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[CpuMetrics] = []
        async for metrics in ws_client.subscribe_cpu_metrics():
            results.append(metrics)

        assert len(results) == 1
        assert isinstance(results[0], CpuMetrics)
        assert results[0].percentTotal == 35.5
        assert len(results[0].cpus) == 2

    async def test_subscribe_cpu_telemetry(self, ws_client: UnraidClient) -> None:
        """Test subscribe_cpu_telemetry yields CpuTelemetryMetrics."""
        from unraid_api.models import CpuTelemetryMetrics

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "systemMetricsCpuTelemetry": {
                            "totalPower": 125.5,
                            "power": 110.0,
                            "temp": 65.0,
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[CpuTelemetryMetrics] = []
        async for metrics in ws_client.subscribe_cpu_telemetry():
            results.append(metrics)

        assert len(results) == 1
        assert isinstance(results[0], CpuTelemetryMetrics)
        assert results[0].totalPower == 125.5
        assert results[0].temp == 65.0

    async def test_subscribe_memory_metrics(self, ws_client: UnraidClient) -> None:
        """Test subscribe_memory_metrics yields MemoryMetrics."""
        from unraid_api.models import MemoryMetrics

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "systemMetricsMemory": {
                            "total": 16777216,
                            "used": 8388608,
                            "free": 8388608,
                            "percentTotal": 50.0,
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[MemoryMetrics] = []
        async for metrics in ws_client.subscribe_memory_metrics():
            results.append(metrics)

        assert len(results) == 1
        assert isinstance(results[0], MemoryMetrics)
        assert results[0].total == 16777216
        assert results[0].percentTotal == 50.0

    async def test_subscribe_ups_updates(self, ws_client: UnraidClient) -> None:
        """Test subscribe_ups_updates yields dicts."""
        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "upsUpdates": {
                            "id": "ups:1",
                            "status": "OL",
                            "battery": {"chargeLevel": 100},
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[dict[str, Any]] = []
        async for data in ws_client.subscribe_ups_updates():
            results.append(data)

        assert len(results) == 1
        assert results[0]["id"] == "ups:1"
        assert results[0]["status"] == "OL"
        assert results[0]["battery"]["chargeLevel"] == 100

    async def test_subscribe_array_updates(self, ws_client: UnraidClient) -> None:
        """Test subscribe_array_updates yields ArraySubscriptionUpdate."""
        from unraid_api.models import ArraySubscriptionUpdate

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "arraySubscription": {
                            "state": "STARTED",
                            "capacity": {
                                "kilobytes": {
                                    "total": 1000000,
                                    "used": 500000,
                                    "free": 500000,
                                }
                            },
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[ArraySubscriptionUpdate] = []
        async for update in ws_client.subscribe_array_updates():
            results.append(update)

        assert len(results) == 1
        assert isinstance(results[0], ArraySubscriptionUpdate)
        assert results[0].state == "STARTED"
        assert results[0].capacity is not None
        assert results[0].capacity.kilobytes.total == 1000000

    async def test_subscribe_temperature_metrics(self, ws_client: UnraidClient) -> None:
        """Test subscribe_temperature_metrics yields TemperatureMetrics."""
        from unraid_api.models import TemperatureMetrics

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "systemMetricsTemperature": {
                            "id": "temp:1",
                            "summary": {
                                "average": 35.0,
                                "warningCount": 0,
                                "criticalCount": 0,
                            },
                            "sensors": [
                                {
                                    "id": "disk:1",
                                    "name": "ST8000VN004",
                                    "type": "DISK",
                                    "current": {
                                        "value": 30.0,
                                        "unit": "CELSIUS",
                                        "status": "NORMAL",
                                    },
                                    "warning": 50,
                                    "critical": 60,
                                }
                            ],
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[TemperatureMetrics] = []
        async for metrics in ws_client.subscribe_temperature_metrics():
            results.append(metrics)

        assert len(results) == 1
        assert isinstance(results[0], TemperatureMetrics)
        assert results[0].id == "temp:1"
        assert results[0].summary is not None
        # Summary is recomputed from visible sensors (one disk @ 30 °C).
        assert results[0].summary.average == 30.0
        assert len(results[0].sensors) == 1
        assert results[0].sensors[0].temperature == 30.0

    async def test_subscribe_notification_added(self, ws_client: UnraidClient) -> None:
        """subscribe_notification_added yields Notification models."""
        from unraid_api.models import Notification

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "notificationAdded": {
                            "id": "notification:abc",
                            "title": "Disk warning",
                            "subject": "Disk 2",
                            "description": "Temperature high",
                            "importance": "WARNING",
                            "link": None,
                            "type": "UNREAD",
                            "timestamp": "2026-04-11T10:00:00Z",
                            "formattedTimestamp": "Apr 11 10:00",
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[Notification] = []
        async for notif in ws_client.subscribe_notification_added():
            results.append(notif)

        assert len(results) == 1
        assert isinstance(results[0], Notification)
        assert results[0].id == "notification:abc"
        assert results[0].importance == "WARNING"

    async def test_subscribe_notifications_overview(
        self, ws_client: UnraidClient
    ) -> None:
        """subscribe_notifications_overview yields NotificationOverview models."""
        from unraid_api.models import NotificationOverview

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "notificationsOverview": {
                            "unread": {
                                "info": 0,
                                "warning": 2,
                                "alert": 1,
                                "total": 3,
                            },
                            "archive": {
                                "info": 10,
                                "warning": 5,
                                "alert": 0,
                                "total": 15,
                            },
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[NotificationOverview] = []
        async for ov in ws_client.subscribe_notifications_overview():
            results.append(ov)

        assert len(results) == 1
        assert isinstance(results[0], NotificationOverview)
        assert results[0].unread.total == 3
        assert results[0].archive.total == 15

    async def test_subscribe_notifications_warnings_and_alerts(
        self, ws_client: UnraidClient
    ) -> None:
        """subscribe_notifications_warnings_and_alerts yields list[Notification]."""
        from unraid_api.models import Notification

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "notificationsWarningsAndAlerts": [
                            {
                                "id": "notification:w1",
                                "title": "Disk",
                                "subject": "Disk 2",
                                "description": "Warning",
                                "importance": "WARNING",
                                "link": None,
                                "type": "UNREAD",
                                "timestamp": None,
                                "formattedTimestamp": None,
                            },
                            {
                                "id": "notification:a1",
                                "title": "Array",
                                "subject": "Array",
                                "description": "Alert",
                                "importance": "ALERT",
                                "link": None,
                                "type": "UNREAD",
                                "timestamp": None,
                                "formattedTimestamp": None,
                            },
                        ]
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[list[Notification]] = []
        async for batch in ws_client.subscribe_notifications_warnings_and_alerts():
            results.append(batch)

        assert len(results) == 1
        assert len(results[0]) == 2
        assert all(isinstance(n, Notification) for n in results[0])
        assert results[0][0].importance == "WARNING"
        assert results[0][1].importance == "ALERT"

    async def test_subscribe_parity_history(self, ws_client: UnraidClient) -> None:
        """subscribe_parity_history yields ParityCheck models."""
        from unraid_api.models import ParityCheck

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "parityHistorySubscription": {
                            "date": "2026-04-11T09:00:00Z",
                            "duration": 1200,
                            "speed": "150.5 MB/s",
                            "status": "RUNNING",
                            "errors": 0,
                            "progress": 42,
                            "correcting": True,
                            "paused": False,
                            "running": True,
                        }
                    }
                },
            }
        )
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[ParityCheck] = []
        async for pc in ws_client.subscribe_parity_history():
            results.append(pc)

        assert len(results) == 1
        assert isinstance(results[0], ParityCheck)
        assert results[0].status == "RUNNING"
        assert results[0].progress == 42
        assert results[0].speed == "150.5 MB/s"
        assert results[0].correcting is True

    async def test_subscribe_owner(self, ws_client: UnraidClient) -> None:
        """subscribe_owner yields Owner models."""
        from unraid_api.models import Owner

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "ownerSubscription": {
                            "username": "admin",
                            "avatar": "https://avatar.url",
                            "url": "https://profile.url",
                        }
                    }
                },
            }
        )
        empty_msg = _ws_text_msg({"id": "test", "type": "next", "payload": {}})
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, empty_msg, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[Owner] = []
        async for owner in ws_client.subscribe_owner():
            results.append(owner)

        assert len(results) == 1
        assert isinstance(results[0], Owner)
        assert results[0].username == "admin"

    async def test_subscribe_servers(self, ws_client: UnraidClient) -> None:
        """subscribe_servers yields Server models."""
        from unraid_api.models import Server

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "serversSubscription": {
                            "id": "server:1",
                            "name": "Tower",
                            "status": "ONLINE",
                        }
                    }
                },
            }
        )
        empty_msg = _ws_text_msg({"id": "test", "type": "next", "payload": {}})
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, empty_msg, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[Server] = []
        async for s in ws_client.subscribe_servers():
            results.append(s)

        assert len(results) == 1
        assert isinstance(results[0], Server)
        assert results[0].name == "Tower"

    async def test_subscribe_plugin_install_updates(
        self, ws_client: UnraidClient
    ) -> None:
        """subscribe_plugin_install_updates yields PluginInstallEvent models."""
        from unraid_api.models import PluginInstallEvent

        ack = _ws_text_msg({"type": "connection_ack"})
        next_msg = _ws_text_msg(
            {
                "id": "test",
                "type": "next",
                "payload": {
                    "data": {
                        "pluginInstallUpdates": {
                            "operationId": "op:1",
                            "status": "RUNNING",
                            "output": ["Extracting files..."],
                            "timestamp": "2026-09-02T00:00:01Z",
                        }
                    }
                },
            }
        )
        empty_msg = _ws_text_msg({"id": "test", "type": "next", "payload": {}})
        complete = _ws_text_msg({"id": "test", "type": "complete"})

        ws = MockWebSocket([ack, empty_msg, next_msg, complete])
        ws_client._session.ws_connect = AsyncMock(return_value=ws)  # type: ignore[union-attr]

        results: list[PluginInstallEvent] = []
        async for evt in ws_client.subscribe_plugin_install_updates("op:1"):
            results.append(evt)

        assert len(results) == 1
        assert isinstance(results[0], PluginInstallEvent)
        assert results[0].operationId == "op:1"
        assert results[0].status == "RUNNING"

        # Assert variable and type were forwarded in subscribe payload
        subscribe_frame = json.loads(ws._send_history[1])
        assert subscribe_frame["type"] == "subscribe"
        assert "$operationId: ID!" in subscribe_frame["payload"]["query"]
        assert subscribe_frame["payload"]["variables"] == {"operationId": "op:1"}
