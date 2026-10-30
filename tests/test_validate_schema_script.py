"""Tests for the SDL schema sources in scripts/validate-schema.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import schema_tools as st

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "upstream"
SDL = FIXTURES / "v4.37.9.graphql"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_schema_script", ROOT / "scripts" / "validate-schema.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_schema_script"] = module
    spec.loader.exec_module(module)
    return module


vs = _load_script()


def _inventory(*documents: str) -> st.Inventory:
    origin = st.Origin("method", st.CLIENT_PATH, 10)
    return st.Inventory(
        [st.Operation(doc, "query", ["method"], [origin]) for doc in documents]
    )


@pytest.fixture
def no_server(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Fail the test if credentials or a client are touched."""
    forbidden = MagicMock(side_effect=AssertionError("server access"))
    monkeypatch.setattr(vs, "load_env", forbidden)
    monkeypatch.setattr(vs, "UnraidClient", forbidden)
    return forbidden


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A mocked server reporting API 4.37.9."""
    client = SimpleNamespace(
        get_version=AsyncMock(
            return_value=SimpleNamespace(unraid="7.2.0", api="4.37.9")
        )
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(vs, "load_env", MagicMock(return_value=("host", "key")))
    monkeypatch.setattr(vs, "UnraidClient", MagicMock(return_value=context))
    return client


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> Any:
    monkeypatch.setattr(sys, "argv", ["validate-schema.py", *args])
    return vs.main()


class TestOfflineSchemaFile:
    async def test_schema_file_needs_no_server(
        self, monkeypatch: pytest.MonkeyPatch, no_server: MagicMock, capsys: Any
    ) -> None:
        monkeypatch.setattr(
            vs, "build_inventory", lambda _schema: _inventory("query { online }")
        )
        code = await _run(monkeypatch, "--schema-file", str(SDL), "--schema-only")
        assert code == 0
        no_server.assert_not_called()
        out = capsys.readouterr().out
        assert "Loading schema from" in out
        assert "1 unique operations in the inventory" in out
        assert "ALL VALIDATIONS PASSED" in out

    @pytest.mark.usefixtures("no_server")
    async def test_failing_operation_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        monkeypatch.setattr(
            vs, "build_inventory", lambda _schema: _inventory("query { nope }")
        )
        code = await _run(monkeypatch, "--schema-file", str(SDL), "--schema-only")
        assert code == 1
        out = capsys.readouterr().out
        assert "[method] src/unraid_api/client.py:10" in out
        assert "Cannot query field 'nope' on type 'Query'." in out

    @pytest.mark.usefixtures("no_server")
    async def test_api_version_fetches_without_a_server(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        urls: list[str] = []

        def fake_get(url: str, token: str | None = None) -> bytes:
            urls.append(url)
            return SDL.read_bytes()

        monkeypatch.setattr(vs, "https_get", fake_get)
        monkeypatch.setattr(
            vs, "build_inventory", lambda _schema: _inventory("query { online }")
        )
        code = await _run(monkeypatch, "--api-version", "v4.37.8", "--schema-only")
        assert code == 0
        assert urls == [st.schema_url("v4.37.8")]


class TestDefaultSource:
    async def test_fetches_sdl_for_server_version(
        self, monkeypatch: pytest.MonkeyPatch, server: SimpleNamespace, capsys: Any
    ) -> None:
        urls: list[str] = []

        def fake_get(url: str, token: str | None = None) -> bytes:
            urls.append(url)
            return SDL.read_bytes()

        monkeypatch.setattr(vs, "https_get", fake_get)
        monkeypatch.setattr(
            vs, "build_inventory", lambda _schema: _inventory("query { online }")
        )
        code = await _run(monkeypatch, "--schema-only")
        assert code == 0
        assert urls == [st.schema_url("v4.37.9")]
        server.get_version.assert_awaited_once()
        assert "Fetching upstream schema for unraid/api v4.37.9" in (
            capsys.readouterr().out
        )

    @pytest.mark.parametrize("api", ["unknown", "4.37", "4.37.9-beta"])
    async def test_unparsable_version_exits_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        server: SimpleNamespace,
        capsys: Any,
        api: str,
    ) -> None:
        server.get_version.return_value = SimpleNamespace(unraid="7", api=api)
        fetch = MagicMock()
        monkeypatch.setattr(vs, "https_get", fetch)
        code = await _run(monkeypatch, "--schema-only")
        assert code == 1
        fetch.assert_not_called()
        out = capsys.readouterr().out
        assert "Pass --schema-file PATH or --api-version X.Y.Z." in out

    async def test_version_lookup_failure_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, server: SimpleNamespace
    ) -> None:
        server.get_version.side_effect = RuntimeError("offline")
        assert await _run(monkeypatch, "--schema-only") == 1

    @pytest.mark.usefixtures("server")
    async def test_fetch_failure_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        def missing(url: str, token: str | None = None) -> bytes:
            raise st.NotFoundError(url, 404, "Not Found")

        monkeypatch.setattr(vs, "https_get", missing)
        assert await _run(monkeypatch, "--schema-only") == 1
        assert "404" in capsys.readouterr().out

    @pytest.mark.usefixtures("server")
    async def test_introspect_keeps_the_live_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        types = vs.schema_types_from_graphql(st.load_sdl(SDL))
        monkeypatch.setattr(vs, "introspect_schema", AsyncMock(return_value=types))
        monkeypatch.setattr(
            vs, "build_inventory", lambda: _inventory("query { online }")
        )
        fetch = MagicMock()
        monkeypatch.setattr(vs, "https_get", fetch)
        assert await _run(monkeypatch, "--introspect", "--schema-only") == 0
        fetch.assert_not_called()


class TestAdapter:
    def test_schema_types_from_graphql(self) -> None:
        schema = st.load_sdl(
            SDL.read_text()
            + "\ninterface Named { name: String }\n"
            + "input Filter { ids: [ID!] }\n"
        )
        types = vs.schema_types_from_graphql(schema)
        assert not [name for name in types if name.startswith("__")]
        docker = types["Query"].fields["docker"]
        assert (docker.type_name, docker.type_kind) == ("Docker", "OBJECT")
        assert docker.is_non_null is False
        containers = types["Docker"].fields["containers"]
        assert containers.is_list is True
        assert containers.is_non_null is True
        assert containers.args == ["skipCache"]
        assert types["Docker"].kind == "OBJECT"
        assert types["Named"].kind == "INTERFACE"
        assert types["Filter"].kind == "INPUT_OBJECT"
        assert types["Filter"].fields["ids"].args == []
        assert types["ContainerState"].kind == "ENUM"
        assert types["ContainerState"].enum_values == ["RUNNING", "EXITED"]
        assert types["JSON"].kind == "SCALAR"
        assert types["DockerContainer"].fields["state"].type_kind == "ENUM"
        assert types["DockerContainer"].fields["labels"].type_kind == "SCALAR"

    @pytest.mark.parametrize(
        ("version", "tag"),
        [("4.37.9", "v4.37.9"), ("v4.37.9", "v4.37.9"), (" 4.37.10 ", "v4.37.10")],
    )
    def test_normalise_api_version(self, version: str, tag: str) -> None:
        assert vs.normalise_api_version(version) == tag
