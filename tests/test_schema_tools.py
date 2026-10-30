"""Tests for the shared schema tooling in script/schema_tools.py."""

from __future__ import annotations

import asyncio
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

import schema_tools as st

if TYPE_CHECKING:
    from graphql import GraphQLSchema

FIXTURES = Path(__file__).parent / "fixtures" / "upstream"
CLIENT_SOURCE = (st.REPO_ROOT / st.CLIENT_PATH).read_text().splitlines()


def _schema(name: str) -> GraphQLSchema:
    return st.load_sdl(FIXTURES / name)


def _write(tmp_path: Path, source: str, name: str = "lib.py") -> str:
    (tmp_path / name).write_text(source)
    return name


def _ops_from(inventory: st.Inventory, function: str) -> list[st.Operation]:
    return [
        op
        for op in inventory.operations
        if any(origin.function == function for origin in op.origins)
    ]


def _line_of(text: str, start: int) -> int:
    """First client.py line at or after `start` (1-based) containing `text`."""
    for number in range(start, len(CLIENT_SOURCE) + 1):
        if text in CLIENT_SOURCE[number - 1]:
            return number
    raise AssertionError(text)


def _def_line(name: str) -> int:
    return _line_of(f"def {name}(", 1)


@pytest.fixture(scope="module")
def schema_v4376() -> GraphQLSchema:
    return _schema("v4.37.6.graphql")


@pytest.fixture(scope="module")
def inventory_v4376(schema_v4376: GraphQLSchema) -> st.Inventory:
    return st.build_inventory(schema_v4376)


class TestExtraction:
    def test_skips_docstrings_and_enforces_keyword_boundary(
        self, tmp_path: Path
    ) -> None:
        path = _write(
            tmp_path,
            '"""query { moduleDoc }"""\n'
            "class Client:\n"
            '    """query { classDoc }"""\n'
            "    def documented(self):\n"
            '        """query { notAnOperation }"""\n'
            '        a = "queryFoo { x }"\n'
            '        b = "query Named($id: ID!) { node(id: $id) { id } }"\n'
            '        c = "{ anonymous }"\n'
            '        d = "mutation { doThing }"\n'
            '        e = "query is slow"\n'
            '        f = "subscription OnEvent { events }"\n'
            "        return a, b, c, d, e, f\n",
        )
        extraction = st.extract_queries_from_source(path, root=tmp_path)
        found = [(q.operation_type, q.query_string) for q in extraction.queries]
        assert found == [
            ("query", "query Named($id: ID!) { node(id: $id) { id } }"),
            ("query", "{ anonymous }"),
            ("mutation", "mutation { doThing }"),
            ("subscription", "subscription OnEvent { events }"),
        ]
        assert all(q.method_name == "documented" for q in extraction.queries)
        assert extraction.queries[0].line_number == 7
        assert extraction.dynamic == []

    def test_records_interpolated_operations_as_dynamic(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "def build(field, name):\n"
            '    label = f"{name}: thing"\n'
            '    return f"query {{ {field} }}", label\n'
            "def skipped(field):\n"
            '    return f"query {{ {field} }}"\n',
        )
        extraction = st.extract_queries_from_source(
            path, root=tmp_path, skip_functions=["skipped"]
        )
        assert extraction.queries == []
        assert extraction.dynamic == [st.DynamicSite("build", path, 3)]

    def test_call_graph_attributes_transitive_public_callers(
        self, tmp_path: Path
    ) -> None:
        path = _write(
            tmp_path,
            "class Client:\n"
            "    def _helper(self):\n"
            '        return "query { thing }"\n'
            "    def typed_thing(self):\n"
            "        return self._helper()\n"
            "    def thing(self, retry=True):\n"
            "        return self.typed_thing() if retry else self.thing(False)\n"
            "    def _orphan(self):\n"
            '        return "query { orphan }"\n',
        )
        inventory = st.build_inventory(root=tmp_path, sources=(path,), registry=())
        methods = {op.document: op.methods for op in inventory.operations}
        assert methods == {
            "query { thing }": ["thing", "typed_thing"],
            "query { orphan }": ["_orphan"],
        }

    def test_unregistered_interpolated_operation_fails(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "class Client:\n"
            "    def build(self, field):\n"
            '        return f"query {{ {field} }}"\n',
        )
        with pytest.raises(st.UnregisteredDynamicOperationError) as err:
            st.build_inventory(root=tmp_path, sources=(path,), registry=())
        assert err.value.sites == [st.DynamicSite("build", path, 3)]
        assert "build (lib.py:3)" in str(err.value)

    def test_identical_documents_merge_provenance(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "class Client:\n"
            "    def one(self):\n"
            '        return "query { same }"\n'
            "    def two(self):\n"
            '        return "query { same }"\n',
        )
        inventory = st.build_inventory(root=tmp_path, sources=(path,), registry=())
        assert len(inventory.operations) == 1
        op = inventory.operations[0]
        assert op.methods == ["one", "two"]
        assert [str(origin) for origin in op.origins] == ["lib.py:3", "lib.py:5"]
        assert op.variants == ["static"]


class TestInventory:
    def test_real_inventory_has_no_unregistered_dynamic_operations(self) -> None:
        inventory = st.build_inventory()
        assert len(inventory.operations) > 100
        # Only the permissive variant without a schema.
        dynamic = [op for op in inventory.operations if "schema" in op.variants]
        assert dynamic == []

    def test_container_selections_are_non_empty_in_both_variants(
        self, inventory_v4376: st.Inventory
    ) -> None:
        for builder in ("_build_containers_query", "_build_containers_query_safe"):
            ops = _ops_from(inventory_v4376, builder)
            variants = {variant for op in ops for variant in op.variants}
            assert variants == {"permissive", "schema"}
            for op in ops:
                assert "containers {" in op.document
                assert "autoStart" in op.document
        full = _ops_from(inventory_v4376, "_build_containers_query")
        permissive = next(op for op in full if "permissive" in op.variants)
        schema = next(op for op in full if "schema" in op.variants)
        assert "tailscaleStatus" in permissive.document
        assert "tailscaleStatus" not in schema.document
        assert "labels" in schema.document

    def test_vm_uuid_only_for_detected_support(
        self, inventory_v4376: st.Inventory
    ) -> None:
        ops = _ops_from(inventory_v4376, "typed_get_vms")
        by_variant = {variant: op for op in ops for variant in op.variants}
        assert "uuid" in by_variant["schema"].document
        assert "uuid" not in by_variant["permissive"].document
        assert by_variant["schema"].methods == ["typed_get_vms"]

        without_uuid = st.load_sdl(
            "type Query { vms: Vms }\n"
            "type Vms { domains: [VmDomain!] }\n"
            "type VmDomain { id: ID! name: String state: String }\n"
        )
        inventory = st.build_inventory(without_uuid)
        documents = [op.document for op in _ops_from(inventory, "typed_get_vms")]
        assert documents
        assert all("uuid" not in document for document in documents)

    def test_capability_introspection_is_in_the_inventory(
        self, inventory_v4376: st.Inventory
    ) -> None:
        (op,) = _ops_from(inventory_v4376, "build_introspection_query")
        assert op.methods == ["get_capabilities"]
        assert op.document.startswith("query ServerCapabilities {")
        assert op.origins[0].path == st.CAPABILITIES_PATH
        assert op.origins[0].dynamic is True

    def test_wrappers_are_attributed(self, inventory_v4376: st.Inventory) -> None:
        networks = [
            op
            for op in inventory_v4376.operations
            if "get_docker_networks" in op.methods
        ]
        assert networks
        assert all("typed_get_docker_networks" in op.methods for op in networks)

    def test_capabilities_from_schema(self, schema_v4376: GraphQLSchema) -> None:
        caps = st.capabilities_from_schema(schema_v4376)
        assert caps.has("VmDomain.uuid")
        assert caps.has("DockerContainer.labels")
        assert not caps.has("DockerContainer.mounts")
        assert not caps.is_permissive

    def test_renderer_must_not_suspend(self) -> None:
        with pytest.raises(RuntimeError, match="must not perform I/O"):
            st._run_without_loop(asyncio.sleep(0))

    def test_renderer_must_send_a_document(self) -> None:
        caps = st.ServerCapabilities.permissive()
        with pytest.raises(RuntimeError, match="sent nothing through query"):
            st._capture(caps, "query", lambda client: client.get_capabilities())

    def test_install_plugin_and_language_render_separately(self) -> None:
        schema = st.load_sdl(
            "type Query { a: Int }\n"
            "type Mutation { unraidPlugins: UnraidPluginsMutations! }\n"
            "input InstallPluginInput { url: String! name: String forced: Boolean }\n"
            "type PluginInstallOperation { id: ID! name: String url: String\n"
            "  status: String output: [String!] createdAt: String\n"
            "  updatedAt: String finishedAt: String }\n"
            "type UnraidPluginsMutations {\n"
            "  installPlugin(input: InstallPluginInput!): PluginInstallOperation!\n"
            "}\n"
        )
        inventory = st.build_inventory(schema)
        ops = _ops_from(inventory, "_install_plugin_operation")
        by_method = {tuple(op.methods): op for op in ops}
        assert set(by_method) == {("install_plugin",), ("install_language",)}
        plugin = by_method[("install_plugin",)]
        language = by_method[("install_language",)]
        assert "installPlugin(input: $input)" in plugin.document
        assert "installLanguage(input: $input)" in language.document
        assert plugin.variants == ["permissive", "schema"]
        # This schema lacks installLanguage, so that server is never sent it.
        assert language.variants == ["permissive"]
        index = st.selected_coordinates(st.load_sdl(_with_language(schema)), inventory)
        assert index["UnraidPluginsMutations.installLanguage"].methods == {
            "install_language"
        }
        assert index["UnraidPluginsMutations.installPlugin"].methods == {
            "install_plugin"
        }
        # The shared literal is no longer extracted statically for both methods.
        assert not [
            op
            for op in inventory.operations
            if {"install_plugin", "install_language"} <= set(op.methods)
        ]


def _with_language(schema: GraphQLSchema) -> str:
    from graphql import print_schema

    return print_schema(schema).replace(
        "installPlugin(input: InstallPluginInput!): PluginInstallOperation!",
        "installPlugin(input: InstallPluginInput!): PluginInstallOperation!\n"
        "  installLanguage(input: InstallPluginInput!): PluginInstallOperation!",
    )


class TestInputUsage:
    SDL = (
        "type Query { a: Int }\n"
        "type Mutation { update(input: ConfigInput!, mode: Mode, n: Int): Boolean }\n"
        "input ConfigInput { enabled: Boolean sensor: SensorInput self: ConfigInput }\n"
        "input SensorInput { id: ID unit: Unit }\n"
        "enum Unit { C F }\n"
        "enum Mode { A B }\n"
        "input Unused { x: Int }\n"
    )

    def test_variable_types_and_nested_inputs_are_tracked(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "class Client:\n"
            "    def update(self):\n"
            '        return """mutation Update(\n'
            "            $input: ConfigInput!, $mode: [Mode!], $n: Int\n"
            '        ) { update(input: $input, mode: $mode, n: $n) }"""\n'
            "    def broken(self):\n"
            '        return "query {"\n',
        )
        inventory = st.build_inventory(root=tmp_path, sources=(path,), registry=())
        index = st.input_usage(st.load_sdl(self.SDL), inventory)
        assert set(index) == {"ConfigInput", "SensorInput", "Unit", "Mode"}
        assert index["Unit"].methods == {"update"}
        assert index["ConfigInput"].locations == {"lib.py:4"}

    def test_required_input_fields_are_marked(self) -> None:
        changes = st.diff_schemas(
            st.load_sdl("type Query { a(i: I): Int } input I { x: Int }"),
            st.load_sdl(
                "type Query { a(i: I): Int }\n"
                "input I { x: Int required: Int! defaulted: Int! = 1 optional: Int }"
            ),
        )
        details = {c.coordinate: c.detail for c in changes}
        assert details == {
            "I.required": "required",
            "I.defaulted": "",
            "I.optional": "",
        }


class TestValidation:
    def test_validate_operation(self, schema_v4376: GraphQLSchema) -> None:
        assert st.validate_operation(schema_v4376, "query { online }") == []
        assert st.validate_operation(schema_v4376, "query { nope }") == [
            "Cannot query field 'nope' on type 'Query'."
        ]
        (syntax,) = st.validate_operation(schema_v4376, "query {")
        assert syntax.startswith("Syntax error:")

    def test_validate_inventory_reports_methods_and_locations(
        self, schema_v4376: GraphQLSchema, inventory_v4376: st.Inventory
    ) -> None:
        failures = st.validate_inventory(schema_v4376, inventory_v4376)
        # The trimmed fixture lacks most of the schema.
        assert failures
        array = next(f for f in failures if "typed_get_array" in f.methods)
        assert array.message == "Cannot query field 'array' on type 'Query'."
        assert array.locations[0].startswith(f"{st.CLIENT_PATH}:")
        assert array.key == (array.document.strip(), array.message)
        # Schema-derived container and VM operations validate; the permissive
        # variants request fields the trimmed fixture does not have.
        failing = {f.document for f in failures}
        for builder in ("_build_containers_query", "typed_get_vms"):
            ops = _ops_from(inventory_v4376, builder)
            schema_op = next(op for op in ops if "schema" in op.variants)
            assert schema_op.document not in failing


class TestCoordinates:
    def test_root_coordinates_map_to_methods_and_lines(
        self, schema_v4376: GraphQLSchema, inventory_v4376: st.Inventory
    ) -> None:
        index = st.selected_coordinates(schema_v4376, inventory_v4376)
        docker = index["Query.docker"]
        assert {
            "typed_get_containers",
            "typed_get_containers_safe",
            "get_containers",
            "get_docker_networks",
            "typed_get_docker_networks",
        } <= docker.methods
        builder = _def_line("_build_containers_query")
        assert f"{st.CLIENT_PATH}:{_line_of('docker {', builder)}" in docker.locations
        get_vms = _def_line("get_vms")
        assert index["Query.vms"].methods == {"get_vms", "typed_get_vms"}
        assert (
            f"{st.CLIENT_PATH}:{_line_of('vms {', get_vms)}"
            in index["Query.vms"].locations
        )
        uuid_line = _line_of('"uuid"', _def_line("typed_get_vms"))
        assert index["VmDomain.uuid"].locations == {f"{st.CLIENT_PATH}:{uuid_line}"}
        assert not [c for c in index if c.startswith("__") or ".__" in c]

    def test_dynamic_field_falls_back_to_builder_line(
        self, inventory_v4376: st.Inventory
    ) -> None:
        origin = st.Origin("typed_get_vms", st.CLIENT_PATH, 1, dynamic=True)
        line = inventory_v4376.field_line(origin, "noSuchFieldAnywhere", 1)
        assert line == _def_line("typed_get_vms")

    def test_unparsable_operations_are_skipped(
        self, schema_v4376: GraphQLSchema
    ) -> None:
        origin = st.Origin("broken", "lib.py", 10)
        inventory = st.Inventory(
            [
                st.Operation("query {", "query", ["broken"], [origin]),
                st.Operation(
                    "query {\n  online\n}", "query", ["fine"], [origin], ["static"]
                ),
            ]
        )
        index = st.selected_coordinates(schema_v4376, inventory)
        assert set(index) == {"Query.online"}
        assert index["Query.online"].locations == {"lib.py:11"}

    def test_merge_selections(self) -> None:
        first = {"A.b": st.Selection({"one"}, {"x:1"})}
        second = {
            "A.b": st.Selection({"two"}, {"x:2"}),
            "C.d": st.Selection({"three"}, {"y:3"}),
        }
        merged = st.merge_selections(first, second)
        assert merged["A.b"].methods == {"one", "two"}
        assert merged["A.b"].locations == {"x:1", "x:2"}
        assert merged["C.d"].methods == {"three"}


class TestSchemaDiff:
    def test_every_diff_kind(self) -> None:
        changes = st.diff_schemas(
            _schema("diff_old.graphql"), _schema("diff_new.graphql")
        )
        ids = [change.id for change in changes]
        assert ids == sorted(ids)
        assert set(ids) == {
            "type_removed:GoneType",
            "type_added:NewType",
            "type_added:Subscription",
            "field_removed:Query.dropped",
            "root_field_added:Query.fresh",
            "field_removed:Kept.removed",
            "field_added:Kept.added",
            "field_added:Named.nick",
            "field_nullable:Kept.becomesNullable:Int!..Int",
            "field_non_null:Kept.becomesNonNull:Int..Int!",
            "field_type_changed:Kept.changesType:Int..String",
            "deprecation_field:Kept.deprecated",
            "arg_removed:Kept.withArgs(dropArg:)",
            "arg_added:Kept.withArgs(newArg:):..Boolean",
            "arg_type_changed:Kept.withArgs(retype:):Int..String",
            "deprecation_arg:Kept.withArgs(deprecateArg:)",
            "input_field_removed:ActInput.removed",
            "input_field_added:ActInput.added:..Int!",
            "input_field_type_changed:ActInput.retyped:Int..String",
            "enum_value_removed:Mode.OLD",
            "enum_value_added:Mode.NEW",
            "deprecation_enum_value:Mode.DEPRECATE",
        }
        deprecated = next(c for c in changes if c.kind == "deprecation_field")
        assert deprecated.detail == "Use something else"

    def test_root_nullability_change(self) -> None:
        changes = st.diff_schemas(
            _schema("v4.37.6.graphql"), _schema("v4.37.9.graphql")
        )
        assert [change.id for change in changes] == [
            "field_nullable:Query.docker:Docker!..Docker",
            "field_nullable:Query.vms:Vms!..Vms",
        ]

    @pytest.mark.parametrize(
        ("kind", "coordinate", "field_coordinate", "type_name"),
        [
            ("field_removed", "Kept.removed", "Kept.removed", "Kept"),
            ("root_field_added", "Query.fresh", "Query.fresh", "Query"),
            ("deprecation_field", "Kept.deprecated", "Kept.deprecated", "Kept"),
            ("arg_removed", "Kept.withArgs(dropArg:)", "Kept.withArgs", "Kept"),
            ("deprecation_arg", "Kept.withArgs(x:)", "Kept.withArgs", "Kept"),
            ("type_removed", "GoneType", None, "GoneType"),
            ("enum_value_added", "Mode.NEW", None, "Mode"),
            ("input_field_added", "ActInput.added", None, "ActInput"),
        ],
    )
    def test_change_coordinates(
        self,
        kind: str,
        coordinate: str,
        field_coordinate: str | None,
        type_name: str,
    ) -> None:
        change = st.SchemaChange(kind, coordinate)
        assert change.field_coordinate == field_coordinate
        assert change.type_name == type_name
        assert change.id == f"{kind}:{coordinate}"


class TestFetch:
    def test_rejects_non_allowlisted_urls(self) -> None:
        for url in (
            "http://api.github.com/x",
            "https://example.com/x",
            "file:///etc/passwd",
        ):
            with pytest.raises(ValueError, match="non-allowlisted"):
                st.https_get(url)

    def test_api_requests_send_token_and_headers(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with patch.object(st.urllib.request, "urlopen", return_value=response) as op:
            assert st.https_get("https://api.github.com/repos/x/y", "tok") == b"{}"
        request = op.call_args.args[0]
        assert request.get_header("Authorization") == "Bearer tok"
        assert request.get_header("Accept") == "application/vnd.github+json"
        assert op.call_args.kwargs["timeout"] == st.FETCH_TIMEOUT

    def test_raw_requests_never_send_the_token(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"type Query { a: Int }"
        with patch.object(st.urllib.request, "urlopen", return_value=response) as op:
            st.https_get(st.schema_url("v4.37.9"), "tok")
        assert op.call_args.args[0].get_header("Authorization") is None

    @pytest.mark.parametrize(
        ("error", "expected", "status"),
        [
            (
                urllib.error.HTTPError("u", 404, "Not Found", {}, None),  # type: ignore[arg-type]
                st.NotFoundError,
                404,
            ),
            (
                urllib.error.HTTPError("u", 500, "Boom", {}, None),  # type: ignore[arg-type]
                st.FetchError,
                500,
            ),
            (urllib.error.URLError("offline"), st.FetchError, None),
        ],
    )
    def test_errors(
        self, error: Exception, expected: type[Exception], status: int | None
    ) -> None:
        with (
            patch.object(st.urllib.request, "urlopen", side_effect=error),
            pytest.raises(expected) as err,
        ):
            st.https_get("https://api.github.com/x")
        assert isinstance(err.value, st.FetchError)
        assert err.value.status == status
        assert "https://api.github.com/x" in str(err.value)

    def test_schema_url(self) -> None:
        assert st.schema_url("v4.37.9") == (
            "https://raw.githubusercontent.com/unraid/api/v4.37.9/"
            "api/generated-schema.graphql"
        )
        sha = "a" * 40
        assert sha in st.schema_url(sha)
        for bad in ("4.37.9", "main", "v4.37.9/../x", "A" * 40):
            with pytest.raises(ValueError, match="Invalid upstream ref"):
                st.schema_url(bad)

    def test_load_sdl_accepts_text_and_paths(self) -> None:
        assert st.load_sdl("type Query { a: Int }").query_type is not None
        assert st.load_sdl(FIXTURES / "v4.37.9.graphql").get_type("Vms") is not None
