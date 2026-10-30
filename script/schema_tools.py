"""Shared GraphQL schema tooling for the upstream watcher and schema validator.

Builds an inventory of every GraphQL operation the library sends, with the
public methods that send it and their source locations, then validates that
inventory against an SDL schema, maps the fields it selects to source lines,
and diffs two schemas into typed changes with stable IDs.

Literal operations are extracted statically. Operations composed at runtime
from server capabilities are rendered through an explicit registry against
two capability sets: `ServerCapabilities.permissive()` and capabilities
derived from the target schema. An interpolated operation that the registry
does not cover fails the inventory, so a new dynamic builder cannot slip by.
"""

from __future__ import annotations

import ast
import functools
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from urllib.parse import urlparse

from graphql import (
    GraphQLEnumType,
    GraphQLError,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLSchema,
    TypeInfo,
    TypeInfoVisitor,
    Undefined,
    Visitor,
    build_schema,
    get_named_type,
    graphql_sync,
    is_introspection_type,
    is_non_null_type,
    is_specified_scalar_type,
    parse,
    validate,
    visit,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from unraid_api.capabilities import (  # noqa: E402
    ServerCapabilities,
    build_introspection_query,
)
from unraid_api.client import UnraidClient  # noqa: E402
from unraid_api.exceptions import UnraidAPIError  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable

    from graphql import FieldNode

CLIENT_PATH = "src/unraid_api/client.py"
CAPABILITIES_PATH = "src/unraid_api/capabilities.py"
SOURCE_PATHS: tuple[str, ...] = (CLIENT_PATH, CAPABILITIES_PATH)

UPSTREAM_REPO = "unraid/api"
UPSTREAM_SCHEMA_PATH = "api/generated-schema.graphql"
ALLOWED_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com"})
FETCH_TIMEOUT = 30
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_OPERATION_RE = re.compile(
    r"^(query|mutation|subscription)(?:\s+[_A-Za-z]\w*)?\s*(?:\([^)]*\))?\s*\{",
    re.DOTALL,
)
_PLACEHOLDER = "\x00"


# =============================================================================
# HTTPS fetch
# =============================================================================


class FetchError(Exception):
    """An HTTPS request failed."""

    def __init__(self, url: str, status: int | None, reason: str) -> None:
        super().__init__(f"GET {url} failed: {status or ''} {reason}".strip())
        self.url = url
        self.status = status


class NotFoundError(FetchError):
    """The requested resource does not exist (HTTP 404)."""


def https_get(url: str, token: str | None = None) -> bytes:
    """GET an allowlisted HTTPS URL and return the body.

    Raises:
        ValueError: The URL is not HTTPS or its host is not allowlisted.
        NotFoundError: The server answered 404.
        FetchError: Any other HTTP or network error.

    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing to fetch non-allowlisted URL: {url}")
    headers = {"User-Agent": "unraid-api-upstream-watch"}
    if parsed.hostname == "api.github.com":
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
            body: bytes = response.read()
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise NotFoundError(url, 404, "Not Found") from err
        raise FetchError(url, err.code, str(err.reason)) from err
    except urllib.error.URLError as err:
        raise FetchError(url, None, str(err.reason)) from err
    return body


def schema_url(ref: str) -> str:
    """Raw URL of the upstream generated schema at a release tag or commit SHA."""
    if not (TAG_RE.match(ref) or SHA_RE.match(ref)):
        raise ValueError(f"Invalid upstream ref: {ref!r}")
    return (
        f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{ref}/"
        f"{UPSTREAM_SCHEMA_PATH}"
    )


# =============================================================================
# SDL loading
# =============================================================================


def load_sdl(source: str | Path) -> GraphQLSchema:
    """Build a schema from SDL text, or from a file when given a `Path`."""
    text = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    return build_schema(text)


# =============================================================================
# Static operation extraction
# =============================================================================


@dataclass(frozen=True)
class ExtractedQuery:
    """A literal GraphQL operation found in library source."""

    method_name: str
    operation_type: str  # query, mutation, subscription
    query_string: str
    line_number: int
    path: str = CLIENT_PATH


@dataclass(frozen=True)
class DynamicSite:
    """An f-string that interpolates into a GraphQL operation."""

    function: str
    path: str
    line_number: int


@dataclass
class Extraction:
    """Result of scanning one source file."""

    queries: list[ExtractedQuery] = field(default_factory=list)
    dynamic: list[DynamicSite] = field(default_factory=list)


@functools.cache
def _read(root: Path, path: str) -> tuple[list[str], ast.Module]:
    """Source lines and AST of a library file, parsed once per run."""
    text = (root / path).read_text(encoding="utf-8")
    return text.splitlines(), ast.parse(text)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _operation_type(text: str) -> str | None:
    stripped = text.lstrip()
    match = _OPERATION_RE.match(stripped)
    if match:
        return match.group(1)
    if stripped.startswith("{"):
        return "query"
    return None


def extract_queries_from_source(
    path: str, *, root: Path = REPO_ROOT, skip_functions: Iterable[str] = ()
) -> Extraction:
    """Extract literal GraphQL operations and interpolated sites from a file.

    Docstrings are skipped and an operation keyword must be followed by an
    optional name, optional variables and a selection set. F-strings that
    interpolate into an operation are recorded as dynamic sites and never
    emitted as operations. Functions in `skip_functions` are rendered by the
    dynamic registry instead and are not scanned.
    """
    tree = _read(root, path)[1]
    docstrings = _docstring_ids(tree)
    skip = set(skip_functions)
    fstring_parts: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            fstring_parts.update(id(child) for child in ast.walk(node))

    result = Extraction()
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name in skip:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.JoinedStr):
                text = "".join(
                    str(v.value) if isinstance(v, ast.Constant) else _PLACEHOLDER
                    for v in node.values
                )
                if _operation_type(text):
                    result.dynamic.append(DynamicSite(func.name, path, node.lineno))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in fstring_parts
                and id(node) not in docstrings
            ):
                op_type = _operation_type(node.value)
                if op_type:
                    result.queries.append(
                        ExtractedQuery(
                            method_name=func.name,
                            operation_type=op_type,
                            query_string=node.value,
                            line_number=node.lineno,
                            path=path,
                        )
                    )
    return result


def build_call_graph(path: str, *, root: Path = REPO_ROOT) -> dict[str, set[str]]:
    """Map each method name to the methods that call it through `self.<name>(`."""
    tree = _read(root, path)[1]
    callers: dict[str, set[str]] = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                callers.setdefault(node.func.attr, set()).add(func.name)
    return callers


def public_callers(method: str, callers: dict[str, set[str]]) -> list[str]:
    """Return the method and its transitive callers that are public, sorted."""
    seen = {method}
    stack = [method]
    while stack:
        for caller in callers.get(stack.pop(), ()):
            if caller not in seen:
                seen.add(caller)
                stack.append(caller)
    public = sorted(name for name in seen if not name.startswith("_"))
    return public or [method]


# =============================================================================
# Dynamic operation registry
# =============================================================================


def _run_without_loop(coro: Coroutine[Any, Any, Any]) -> Any:
    """Drive a coroutine that never suspends; rendering performs no I/O."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    coro.close()
    raise RuntimeError("Operation renderer suspended; it must not perform I/O")


def _render_client(caps: ServerCapabilities) -> UnraidClient:
    client = UnraidClient("upstream-watch.invalid", "unused-api-key")
    client._capabilities = caps
    return client


def _render_containers(caps: ServerCapabilities) -> str:
    return _render_client(caps)._build_containers_query(caps)


def _render_containers_safe(caps: ServerCapabilities) -> str:
    return _render_client(caps)._build_containers_query_safe(caps)


class _Sent(Exception):
    """Raised by the recording transport once the document has been sent."""


def _capture(
    caps: ServerCapabilities,
    transport: str,
    call: Callable[[UnraidClient], Coroutine[Any, Any, Any]],
) -> str | None:
    """Record the document a client method sends through `transport`.

    Returns None when the method refuses to send for these capabilities.
    """
    client = _render_client(caps)
    recorder = AsyncMock(side_effect=_Sent)
    setattr(client, transport, recorder)
    try:
        _run_without_loop(call(client))
    except _Sent:
        return str(recorder.call_args.args[0])
    except UnraidAPIError:
        return None
    raise RuntimeError(f"Renderer sent nothing through {transport}()")


def _render_vms(caps: ServerCapabilities) -> str | None:
    return _capture(caps, "query", lambda client: client.typed_get_vms())


def _render_install_plugin(caps: ServerCapabilities) -> str | None:
    return _capture(caps, "mutate", lambda client: client.install_plugin("u"))


def _render_install_language(caps: ServerCapabilities) -> str | None:
    return _capture(caps, "mutate", lambda client: client.install_language("u"))


def _render_introspection(_caps: ServerCapabilities) -> str:
    return build_introspection_query()


@dataclass(frozen=True)
class DynamicSource:
    """A runtime-composed operation and how to render it."""

    function: str
    path: str
    # Returns None when the operation is not sent for these capabilities.
    render: Callable[[ServerCapabilities], str | None]
    # Methods to attribute the operation to; None means the function's
    # transitive public callers.
    methods: tuple[str, ...] | None = None


DYNAMIC_REGISTRY: tuple[DynamicSource, ...] = (
    DynamicSource("_build_containers_query", CLIENT_PATH, _render_containers),
    DynamicSource("_build_containers_query_safe", CLIENT_PATH, _render_containers_safe),
    DynamicSource("typed_get_vms", CLIENT_PATH, _render_vms),
    # One literal document; the field is swapped per public method at runtime.
    DynamicSource(
        "_install_plugin_operation",
        CLIENT_PATH,
        _render_install_plugin,
        methods=("install_plugin",),
    ),
    DynamicSource(
        "_install_plugin_operation",
        CLIENT_PATH,
        _render_install_language,
        methods=("install_language",),
    ),
    # Every capability-gated method awaits get_capabilities(); attributing the
    # introspection query to all of them would bury the one method that sends it.
    DynamicSource(
        "build_introspection_query",
        CAPABILITIES_PATH,
        _render_introspection,
        methods=("get_capabilities",),
    ),
)


class UnregisteredDynamicOperationError(Exception):
    """An interpolated operation f-string is not in the dynamic registry."""

    def __init__(self, sites: list[DynamicSite]) -> None:
        listed = ", ".join(f"{s.function} ({s.path}:{s.line_number})" for s in sites)
        super().__init__(
            "Interpolated GraphQL operations missing from DYNAMIC_REGISTRY: " + listed
        )
        self.sites = sites


def capabilities_from_schema(schema: GraphQLSchema) -> ServerCapabilities:
    """Derive the capabilities a server with this schema would report."""
    result = graphql_sync(schema, build_introspection_query())
    return ServerCapabilities.from_introspection_response(result.data or {})


# =============================================================================
# Inventory
# =============================================================================


@dataclass(frozen=True)
class Origin:
    """Where an operation is defined in library source."""

    function: str
    path: str
    line: int
    dynamic: bool = False

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class Operation:
    """One unique GraphQL document the library sends."""

    document: str
    operation_type: str
    methods: list[str]
    origins: list[Origin]
    variants: list[str] = field(default_factory=list)


@functools.cache
def _function_lines(path: str, root: Path) -> dict[str, tuple[int, int, int]]:
    """Map function name to (def line, first body line after docstring, end line)."""
    tree = _read(root, path)[1]
    docstrings = _docstring_ids(tree)
    lines: dict[str, tuple[int, int, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0]
            start = first.lineno
            if isinstance(first, ast.Expr) and id(first.value) in docstrings:
                start = (first.end_lineno or first.lineno) + 1
            lines[node.name] = (node.lineno, start, node.end_lineno or node.lineno)
    return lines


@dataclass
class Inventory:
    """Every operation the library sends, with provenance."""

    operations: list[Operation]
    root: Path = REPO_ROOT

    def field_line(self, origin: Origin, field_name: str, doc_line: int) -> int:
        """Source line for a field selected by an operation from `origin`."""
        if not origin.dynamic:
            return origin.line + doc_line - 1
        def_line, start, end = _function_lines(origin.path, self.root)[origin.function]
        source = _read(self.root, origin.path)[0]
        pattern = re.compile(rf"\b{re.escape(field_name)}\b")
        for number in range(start, end + 1):
            if pattern.search(source[number - 1]):
                return number
        return def_line


def build_inventory(
    schema: GraphQLSchema | None = None,
    *,
    root: Path = REPO_ROOT,
    sources: tuple[str, ...] = SOURCE_PATHS,
    registry: tuple[DynamicSource, ...] = DYNAMIC_REGISTRY,
) -> Inventory:
    """Build the library operation inventory.

    Dynamic sources are rendered with permissive capabilities and, when a
    schema is given, with capabilities derived from that schema. Identical
    documents are merged, keeping every method and origin.
    """
    callers: dict[str, set[str]] = {}
    for path in sources:
        for name, names in build_call_graph(path, root=root).items():
            callers.setdefault(name, set()).update(names)

    by_key: dict[str, Operation] = {}

    def add(
        document: str, op_type: str, methods: list[str], origin: Origin, variant: str
    ) -> None:
        key = document.strip()
        op = by_key.get(key)
        if op is None:
            op = by_key[key] = Operation(document, op_type, [], [], [])
        op.methods = sorted(set(op.methods) | set(methods))
        if origin not in op.origins:
            op.origins.append(origin)
        if variant not in op.variants:
            op.variants.append(variant)

    unregistered: list[DynamicSite] = []
    for path in sources:
        skip = [d.function for d in registry if d.path == path]
        extraction = extract_queries_from_source(path, root=root, skip_functions=skip)
        unregistered.extend(extraction.dynamic)
        for eq in extraction.queries:
            add(
                eq.query_string,
                eq.operation_type,
                public_callers(eq.method_name, callers),
                Origin(eq.method_name, path, eq.line_number),
                "static",
            )
    if unregistered:
        raise UnregisteredDynamicOperationError(unregistered)

    variants: list[tuple[str, ServerCapabilities]] = [
        ("permissive", ServerCapabilities.permissive())
    ]
    if schema is not None:
        variants.append(("schema", capabilities_from_schema(schema)))
    for source in registry:
        def_line = _function_lines(source.path, root)[source.function][0]
        methods = (
            list(source.methods)
            if source.methods is not None
            else public_callers(source.function, callers)
        )
        origin = Origin(source.function, source.path, def_line, dynamic=True)
        for variant, caps in variants:
            document = source.render(caps)
            if document is None:
                continue
            op_type = _operation_type(document) or "query"
            add(document, op_type, methods, origin, variant)

    return Inventory(list(by_key.values()), root)


# =============================================================================
# Validation
# =============================================================================


_SUGGESTION_RE = re.compile(r"\s*Did you mean .*\?$", re.DOTALL)


@dataclass(frozen=True)
class ValidationFailure:
    """A library operation that does not validate against a schema."""

    methods: tuple[str, ...]
    locations: tuple[str, ...]
    message: str
    document: str

    @property
    def stable_message(self) -> str:
        """The message without "Did you mean ...?" suggestions.

        graphql-core suggests names from the whole schema, so an unrelated
        addition would otherwise change the message of a known failure.
        """
        return _SUGGESTION_RE.sub("", self.message)

    @property
    def key(self) -> tuple[str, str]:
        return (self.document.strip(), self.stable_message)


def validate_operation(schema: GraphQLSchema, document: str) -> list[str]:
    """Return graphql-core validation messages for one document."""
    try:
        ast_document = parse(document)
    except GraphQLError as err:
        return [f"Syntax error: {err.message}"]
    return [err.message for err in validate(schema, ast_document)]


def validate_inventory(
    schema: GraphQLSchema, inventory: Inventory
) -> list[ValidationFailure]:
    """Validate every inventory operation against `schema`."""
    failures: list[ValidationFailure] = []
    for op in inventory.operations:
        for message in validate_operation(schema, op.document):
            failures.append(
                ValidationFailure(
                    methods=tuple(op.methods),
                    locations=tuple(str(o) for o in op.origins),
                    message=message,
                    document=op.document,
                )
            )
    return failures


# =============================================================================
# Selected coordinates
# =============================================================================


@dataclass
class Selection:
    """Who selects a schema coordinate, and where."""

    methods: set[str] = field(default_factory=set)
    locations: set[str] = field(default_factory=set)


SelectionIndex = dict[str, Selection]


class _FieldCollector(Visitor):
    """Collect (coordinate, field name, document line) for every schema field."""

    def __init__(self, type_info: TypeInfo) -> None:
        super().__init__()
        self.type_info = type_info
        self.found: list[tuple[str, str, int]] = []

    def enter_field(self, node: FieldNode, *_args: Any) -> None:
        parent = self.type_info.get_parent_type()
        name = node.name.value
        if (
            parent is None
            or parent.name.startswith("__")
            or name.startswith("__")
            or self.type_info.get_field_def() is None
        ):
            return
        line = node.loc.start_token.line if node.loc else 1
        self.found.append((f"{parent.name}.{name}", name, line))


def selected_coordinates(schema: GraphQLSchema, inventory: Inventory) -> SelectionIndex:
    """Map each selected `Type.field` coordinate to methods and `file:line`."""
    index: SelectionIndex = {}
    for op in inventory.operations:
        try:
            document = parse(op.document)
        except GraphQLError:
            continue
        type_info = TypeInfo(schema)
        collector = _FieldCollector(type_info)
        visit(document, TypeInfoVisitor(type_info, collector))
        found = collector.found
        for coordinate, name, doc_line in found:
            entry = index.setdefault(coordinate, Selection())
            entry.methods.update(op.methods)
            for origin in op.origins:
                line = inventory.field_line(origin, name, doc_line)
                entry.locations.add(f"{origin.path}:{line}")
    return index


def _input_closure(schema: GraphQLSchema, type_name: str) -> list[str]:
    """Input object and enum types reachable from `type_name`, itself included."""
    found: list[str] = []
    stack = [type_name]
    while stack:
        name = stack.pop()
        gql_type = schema.get_type(name)
        if name in found or not isinstance(
            gql_type, (GraphQLInputObjectType, GraphQLEnumType)
        ):
            continue
        found.append(name)
        if isinstance(gql_type, GraphQLInputObjectType):
            stack.extend(get_named_type(f.type).name for f in gql_type.fields.values())
    return found


def input_usage(schema: GraphQLSchema, inventory: Inventory) -> SelectionIndex:
    """Map input object and enum types sent in variables to methods and `file:line`.

    Covers the types named by each operation's variable definitions and every
    input type and enum reachable through their fields. `graphql.validate`
    cannot see breakage inside these, because variable values are not part of
    the document.
    """
    index: SelectionIndex = {}
    for op in inventory.operations:
        try:
            document = parse(op.document)
        except GraphQLError:
            continue
        for definition in document.definitions:
            for variable in getattr(definition, "variable_definitions", None) or ():
                type_node = variable.type
                while not hasattr(type_node, "name"):
                    type_node = type_node.type
                doc_line = variable.loc.start_token.line if variable.loc else 1
                name = variable.variable.name.value
                for type_name in _input_closure(schema, type_node.name.value):
                    entry = index.setdefault(type_name, Selection())
                    entry.methods.update(op.methods)
                    for origin in op.origins:
                        line = inventory.field_line(origin, name, doc_line)
                        entry.locations.add(f"{origin.path}:{line}")
    return index


def merge_selections(*indexes: SelectionIndex) -> SelectionIndex:
    """Union several selection indexes."""
    merged: SelectionIndex = {}
    for index in indexes:
        for coordinate, selection in index.items():
            entry = merged.setdefault(coordinate, Selection())
            entry.methods.update(selection.methods)
            entry.locations.update(selection.locations)
    return merged


# =============================================================================
# Schema diff
# =============================================================================


@dataclass(frozen=True)
class SchemaChange:
    """One typed difference between two schemas."""

    kind: str
    coordinate: str
    before: str | None = None
    after: str | None = None
    detail: str = ""

    @property
    def id(self) -> str:
        """Stable identifier: kind, coordinate and before/after values."""
        parts = [self.kind, self.coordinate]
        if self.before is not None or self.after is not None:
            parts.append(f"{self.before or ''}..{self.after or ''}")
        return ":".join(parts)

    @property
    def field_coordinate(self) -> str | None:
        """The `Type.field` coordinate whose selection this change affects."""
        if self.kind.startswith(("field_", "root_field_", "deprecation_field")):
            return self.coordinate
        if self.kind.startswith(("arg_", "deprecation_arg")):
            return self.coordinate.split("(", 1)[0]
        return None

    @property
    def type_name(self) -> str:
        return self.coordinate.split(".", 1)[0].split("(", 1)[0]


def _named_types(schema: GraphQLSchema) -> dict[str, Any]:
    return {
        name: gql_type
        for name, gql_type in schema.type_map.items()
        if not is_introspection_type(gql_type)
        and not is_specified_scalar_type(gql_type)
    }


def _root_names(schema: GraphQLSchema) -> set[str]:
    roots = (schema.query_type, schema.mutation_type, schema.subscription_type)
    return {root.name for root in roots if root is not None}


def _type_change_kind(before: str, after: str) -> str:
    if before == f"{after}!":
        return "field_nullable"
    if after == f"{before}!":
        return "field_non_null"
    return "field_type_changed"


def diff_schemas(old: GraphQLSchema, new: GraphQLSchema) -> list[SchemaChange]:
    """Return every change from `old` to `new`, sorted by ID."""
    changes: list[SchemaChange] = []
    old_types, new_types = _named_types(old), _named_types(new)
    roots = _root_names(new)

    for name in sorted(old_types.keys() - new_types.keys()):
        changes.append(SchemaChange("type_removed", name))
    for name in sorted(new_types.keys() - old_types.keys()):
        changes.append(SchemaChange("type_added", name))

    for name in sorted(old_types.keys() & new_types.keys()):
        old_type, new_type = old_types[name], new_types[name]
        if isinstance(old_type, (GraphQLObjectType, GraphQLInterfaceType)) and (
            isinstance(new_type, (GraphQLObjectType, GraphQLInterfaceType))
        ):
            changes.extend(_diff_fields(name, old_type, new_type, name in roots))
        elif isinstance(old_type, GraphQLInputObjectType) and isinstance(
            new_type, GraphQLInputObjectType
        ):
            changes.extend(_diff_input_fields(name, old_type, new_type))
        elif isinstance(old_type, GraphQLEnumType) and isinstance(
            new_type, GraphQLEnumType
        ):
            changes.extend(_diff_enum(name, old_type, new_type))
    return sorted(changes, key=lambda change: change.id)


def _diff_fields(
    type_name: str,
    old_type: GraphQLObjectType | GraphQLInterfaceType,
    new_type: GraphQLObjectType | GraphQLInterfaceType,
    is_root: bool,
) -> list[SchemaChange]:
    changes: list[SchemaChange] = []
    old_fields, new_fields = old_type.fields, new_type.fields
    for name in old_fields.keys() - new_fields.keys():
        changes.append(SchemaChange("field_removed", f"{type_name}.{name}"))
    for name in new_fields.keys() - old_fields.keys():
        kind = "root_field_added" if is_root else "field_added"
        changes.append(SchemaChange(kind, f"{type_name}.{name}"))
    for name in old_fields.keys() & new_fields.keys():
        coordinate = f"{type_name}.{name}"
        old_field, new_field = old_fields[name], new_fields[name]
        before, after = str(old_field.type), str(new_field.type)
        if before != after:
            changes.append(
                SchemaChange(
                    _type_change_kind(before, after), coordinate, before, after
                )
            )
        if new_field.deprecation_reason and not old_field.deprecation_reason:
            changes.append(
                SchemaChange(
                    "deprecation_field", coordinate, detail=new_field.deprecation_reason
                )
            )
        for arg in old_field.args.keys() - new_field.args.keys():
            changes.append(SchemaChange("arg_removed", f"{coordinate}({arg}:)"))
        for arg in new_field.args.keys() - old_field.args.keys():
            changes.append(
                SchemaChange(
                    "arg_added",
                    f"{coordinate}({arg}:)",
                    after=str(new_field.args[arg].type),
                )
            )
        for arg in old_field.args.keys() & new_field.args.keys():
            old_arg, new_arg = old_field.args[arg], new_field.args[arg]
            arg_coordinate = f"{coordinate}({arg}:)"
            if str(old_arg.type) != str(new_arg.type):
                changes.append(
                    SchemaChange(
                        "arg_type_changed",
                        arg_coordinate,
                        str(old_arg.type),
                        str(new_arg.type),
                    )
                )
            if new_arg.deprecation_reason and not old_arg.deprecation_reason:
                changes.append(
                    SchemaChange(
                        "deprecation_arg",
                        arg_coordinate,
                        detail=new_arg.deprecation_reason,
                    )
                )
    return changes


def _diff_input_fields(
    type_name: str, old_type: GraphQLInputObjectType, new_type: GraphQLInputObjectType
) -> list[SchemaChange]:
    changes: list[SchemaChange] = []
    old_fields, new_fields = old_type.fields, new_type.fields
    for name in old_fields.keys() - new_fields.keys():
        changes.append(SchemaChange("input_field_removed", f"{type_name}.{name}"))
    for name in new_fields.keys() - old_fields.keys():
        new_field = new_fields[name]
        required = is_non_null_type(new_field.type) and not _has_default(new_field)
        changes.append(
            SchemaChange(
                "input_field_added",
                f"{type_name}.{name}",
                after=str(new_field.type),
                detail="required" if required else "",
            )
        )
    for name in old_fields.keys() & new_fields.keys():
        old_field, new_field = old_fields[name], new_fields[name]
        before, after = str(old_field.type), str(new_field.type)
        if before != after:
            changes.append(
                SchemaChange(
                    "input_field_type_changed", f"{type_name}.{name}", before, after
                )
            )
        elif (
            is_non_null_type(new_field.type)
            and _has_default(old_field)
            and not _has_default(new_field)
        ):
            # The field becomes mandatory for callers that omitted it.
            changes.append(
                SchemaChange(
                    "input_field_default_removed", f"{type_name}.{name}", after=after
                )
            )
    return changes


def _has_default(input_field: Any) -> bool:
    # graphql-core 3.3 keeps SDL defaults in `default`; 3.2 in `default_value`.
    return (
        getattr(input_field, "default", None) is not None
        or input_field.default_value is not Undefined
    )


def _diff_enum(
    type_name: str, old_type: GraphQLEnumType, new_type: GraphQLEnumType
) -> list[SchemaChange]:
    changes: list[SchemaChange] = []
    old_values, new_values = old_type.values, new_type.values
    for name in old_values.keys() - new_values.keys():
        changes.append(SchemaChange("enum_value_removed", f"{type_name}.{name}"))
    for name in new_values.keys() - old_values.keys():
        changes.append(SchemaChange("enum_value_added", f"{type_name}.{name}"))
    for name in old_values.keys() & new_values.keys():
        reason = new_values[name].deprecation_reason
        if reason and not old_values[name].deprecation_reason:
            changes.append(
                SchemaChange(
                    "deprecation_enum_value", f"{type_name}.{name}", detail=reason
                )
            )
    return changes
