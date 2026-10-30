#!/usr/bin/env python3
"""Unraid API ↔ GraphQL Schema Validator.

This script validates that every GraphQL query, mutation, and subscription
in the unraid-api client library is compatible with the Unraid API schema.
It catches field renames, removed fields, changed nesting (e.g., the
capacity { kilobytes { ... } } issue from #196), and type mismatches BEFORE
they hit production.

The schema source is, in order of precedence:
  --schema-file PATH   an SDL file (offline with --schema-only)
  --api-version X.Y.Z  the upstream SDL (api/generated-schema.graphql) at vX.Y.Z
  --introspect         live introspection (refused by Unraid API 4.37.8+)
  default              the upstream SDL for the server's reported API version

How it works:
  1. Loads the schema from one of the sources above
  2. Builds the library operation inventory (script/schema_tools.py)
  3. Validates every operation with graphql.validate (SDL sources)
  4. Runs every client method against the live server
  5. Validates response data matches Pydantic models
  6. Reports any schema mismatches, missing fields, or validation errors

Usage:
  python scripts/validate-schema.py                 # Run all validations
  python scripts/validate-schema.py --schema-only   # Only load schema + validate fields
  python scripts/validate-schema.py --schema-file api.graphql --schema-only  # Offline
  python scripts/validate-schema.py --live-only     # Only run live method tests
  python scripts/validate-schema.py --dump-schema   # Dump the schema type map to JSON

Reads credentials from scripts/.env or UNRAID_HOST/UNRAID_API_KEY env vars.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure the local src and the shared schema tooling are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "script"))

from graphql import (  # noqa: E402
    GraphQLEnumType,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLSchema,
    get_named_type,
    is_list_type,
    is_non_null_type,
)
from schema_tools import (  # noqa: E402
    ExtractedQuery,
    FetchError,
    build_inventory,
    https_get,
    load_sdl,
    schema_url,
    validate_inventory,
)

from unraid_api import UnraidClient  # noqa: E402


# =============================================================================
# Credential Loading
# =============================================================================


def _sanitize_host(host: str) -> str:
    if "://" in host:
        from urllib.parse import urlparse

        parsed = urlparse(host)
        return parsed.hostname or "***"
    if "@" in host:
        return host.split("@", 1)[1]
    return host


def load_env() -> tuple[str, str]:
    """Load host and API key from scripts/.env, .env, or environment variables."""
    host = os.environ.get("UNRAID_HOST", "")
    api_key = os.environ.get("UNRAID_API_KEY", "")

    if not host or not api_key:
        env_paths = [
            Path(__file__).resolve().parent / ".env",
            Path(__file__).resolve().parent.parent / ".env",
        ]
        for env_path in env_paths:
            if env_path.exists():
                lines = [line.strip() for line in env_path.read_text().splitlines()]
                for i, line in enumerate(lines):
                    if line.startswith("IP:"):
                        host = host or line.split(":", 1)[1].strip()
                    elif line.startswith("API Key:"):
                        api_key = api_key or line.split(":", 1)[1].strip()
                    elif line == "Unraid IP Address:" and i + 1 < len(lines):
                        host = host or lines[i + 1]
                    elif line == "Unraid API Key:" and i + 1 < len(lines):
                        api_key = api_key or lines[i + 1]
                    elif line.startswith("UNRAID_HOST="):
                        host = host or line.split("=", 1)[1].strip().strip('"\'')
                    elif line.startswith("UNRAID_API_KEY="):
                        api_key = api_key or line.split("=", 1)[1].strip().strip('"\'')
            if host and api_key:
                break

    if not host or not api_key:
        print("ERROR: Could not find credentials.")
        print("Set UNRAID_HOST/UNRAID_API_KEY env vars or create scripts/.env with:")
        print("  IP: 192.168.x.x")
        print("  API Key: your-key")
        sys.exit(1)

    return host, api_key


# =============================================================================
# Schema Introspection
# =============================================================================

# Unraid blocks __schema introspection but allows __type queries.
# We use __type to introspect individual types, starting from known roots
# and recursively following field types.

INTROSPECTION_TYPE_QUERY = """
query IntrospectType($name: String!) {
    __type(name: $name) {
        kind
        name
        fields {
            name
            args {
                name
                type {
                    kind
                    name
                    ofType {
                        kind
                        name
                        ofType { kind name ofType { kind name } }
                    }
                }
            }
            type {
                kind
                name
                ofType {
                    kind
                    name
                    ofType { kind name ofType { kind name } }
                }
            }
        }
        inputFields {
            name
            type {
                kind
                name
                ofType { kind name ofType { kind name } }
            }
        }
        enumValues { name }
    }
}
"""


@dataclass
class SchemaField:
    """A field in a GraphQL type."""

    name: str
    type_name: str | None
    type_kind: str
    is_list: bool = False
    is_non_null: bool = False
    args: list[str] = field(default_factory=list)


@dataclass
class SchemaType:
    """A GraphQL type with its fields."""

    name: str
    kind: str
    fields: dict[str, SchemaField] = field(default_factory=dict)
    enum_values: list[str] = field(default_factory=list)


def _unwrap_type(type_info: dict[str, Any]) -> tuple[str | None, str, bool, bool]:
    """Unwrap a GraphQL type to get the base type name."""
    is_non_null = False
    is_list = False
    current = type_info

    while current:
        kind = current.get("kind", "")
        name = current.get("name")

        if kind == "NON_NULL":
            is_non_null = True
            current = current.get("ofType", {})
        elif kind == "LIST":
            is_list = True
            current = current.get("ofType", {})
        else:
            return name, kind, is_list, is_non_null

    return None, "UNKNOWN", is_list, is_non_null


def parse_schema(introspection_result: dict[str, Any]) -> dict[str, SchemaType]:
    """Parse introspection result into a type map."""
    schema_data = introspection_result.get("__schema", {})
    types: dict[str, SchemaType] = {}

    for type_data in schema_data.get("types", []):
        name = type_data.get("name", "")
        if name.startswith("__"):
            continue  # Skip introspection types

        schema_type = SchemaType(
            name=name,
            kind=type_data.get("kind", ""),
        )

        # Parse fields
        for field_data in type_data.get("fields") or []:
            field_name = field_data.get("name", "")
            type_info = field_data.get("type", {})
            type_name, type_kind, is_list, is_non_null = _unwrap_type(type_info)
            args = [a.get("name", "") for a in (field_data.get("args") or [])]

            schema_type.fields[field_name] = SchemaField(
                name=field_name,
                type_name=type_name,
                type_kind=type_kind,
                is_list=is_list,
                is_non_null=is_non_null,
                args=args,
            )

        # Parse enum values
        for ev in type_data.get("enumValues") or []:
            schema_type.enum_values.append(ev.get("name", ""))

        types[name] = schema_type

    return types


async def introspect_schema(client: UnraidClient) -> dict[str, SchemaType]:
    """Crawl the GraphQL schema by introspecting types starting from roots.

    Since Unraid blocks __schema introspection, we use __type queries
    to walk from Query/Mutation/Subscription roots through all reachable types.
    """
    types: dict[str, SchemaType] = {}
    queue: list[str] = ["Query", "Mutation", "Subscription"]
    visited: set[str] = set()

    while queue:
        type_name = queue.pop(0)
        if type_name in visited or type_name.startswith("__"):
            continue
        visited.add(type_name)

        try:
            result = await client.query(
                INTROSPECTION_TYPE_QUERY, {"name": type_name}
            )
        except Exception as e:
            print(f"  WARNING: Could not introspect '{type_name}': {e}")
            continue

        type_data = result.get("__type")
        if type_data is None:
            continue

        schema_type = SchemaType(
            name=type_data.get("name", type_name),
            kind=type_data.get("kind", ""),
        )

        for field_data in type_data.get("fields") or []:
            field_name = field_data.get("name", "")
            type_info = field_data.get("type", {})
            f_type_name, type_kind, is_list, is_non_null = _unwrap_type(type_info)
            args = [a.get("name", "") for a in (field_data.get("args") or [])]
            schema_type.fields[field_name] = SchemaField(
                name=field_name,
                type_name=f_type_name,
                type_kind=type_kind,
                is_list=is_list,
                is_non_null=is_non_null,
                args=args,
            )

            # Queue the field's type for introspection if it's an object type
            if f_type_name and f_type_name not in visited:
                queue.append(f_type_name)

        for ev in type_data.get("enumValues") or []:
            schema_type.enum_values.append(ev.get("name", ""))

        types[type_name] = schema_type

    print(f"  Crawled {len(types)} types from schema")
    return types





# =============================================================================
# GraphQL Field Validation Against Schema
# =============================================================================


@dataclass
class ValidationIssue:
    """A schema validation issue found."""

    method_name: str
    severity: str  # ERROR, WARNING, INFO
    message: str
    field_path: str


def _parse_graphql_selection_set(
    text: str,
) -> list[tuple[str, str | None]]:
    """Simple parser for GraphQL selection sets.

    Returns list of (field_name, sub_selection_text_or_None).
    This is a simplified parser - doesn't handle fragments or aliases.
    """
    results: list[tuple[str, str | None]] = []
    i = 0
    text = text.strip()

    while i < len(text):
        # Skip whitespace and commas
        while i < len(text) and text[i] in " \t\n\r,":
            i += 1
        if i >= len(text):
            break

        # Skip comments
        if text[i] == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue

        # Read field name (may include directives/args)
        field_start = i
        while i < len(text) and text[i] not in " \t\n\r{(,}":
            i += 1
        field_name = text[field_start:i].strip()

        if not field_name or field_name == "...":
            i += 1
            continue

        # Skip arguments ( ... )
        while i < len(text) and text[i] in " \t\n\r":
            i += 1
        if i < len(text) and text[i] == "(":
            depth = 1
            i += 1
            while i < len(text) and depth > 0:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1

        # Check for sub-selection { ... }
        while i < len(text) and text[i] in " \t\n\r":
            i += 1
        sub_selection = None
        if i < len(text) and text[i] == "{":
            depth = 1
            start = i + 1
            i += 1
            while i < len(text) and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            sub_selection = text[start : i - 1].strip()

        if field_name and field_name not in ("query", "mutation", "subscription"):
            # Skip aliases: if field_name contains ':', take the part after it
            if ":" in field_name:
                field_name = field_name.split(":", 1)[1].strip()
            results.append((field_name, sub_selection))

    return results


def _extract_body(query_str: str) -> str:
    """Extract the body of a GraphQL operation (inside the outermost braces)."""
    # Strip operation type and name
    stripped = query_str.strip()

    # Handle named operations: query QueryName($var: Type!) { ... }
    for prefix in ("query", "mutation", "subscription"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
            break

    # Skip operation name and variables
    if stripped and stripped[0] != "{":
        # Skip to the first {
        idx = stripped.find("{")
        if idx >= 0:
            stripped = stripped[idx:]

    # Remove outer braces
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped[1:-1].strip()
    return stripped


def validate_selection(
    fields: list[tuple[str, str | None]],
    schema_type: SchemaType,
    schema_types: dict[str, SchemaType],
    path: str,
    method_name: str,
) -> list[ValidationIssue]:
    """Recursively validate a selection set against the schema."""
    issues: list[ValidationIssue] = []

    for field_name, sub_selection in fields:
        field_path = f"{path}.{field_name}"

        # Check if field exists on the type
        if field_name not in schema_type.fields:
            # Check for close matches (typos or renames)
            available = list(schema_type.fields.keys())
            close = [
                f for f in available if _similar(field_name, f)
            ]
            suggestion = ""
            if close:
                suggestion = f" Did you mean: {', '.join(close)}?"

            issues.append(
                ValidationIssue(
                    method_name=method_name,
                    severity="ERROR",
                    message=(
                        f"Field '{field_name}' does not exist on type"
                        f" '{schema_type.name}'.{suggestion}"
                        f" Available fields: {', '.join(sorted(available))}"
                    ),
                    field_path=field_path,
                )
            )
            continue

        schema_field = schema_type.fields[field_name]

        # If there's a sub-selection, validate it recursively
        if sub_selection:
            # Resolve the target type
            target_type_name = schema_field.type_name
            if target_type_name and target_type_name in schema_types:
                sub_fields = _parse_graphql_selection_set(sub_selection)
                sub_issues = validate_selection(
                    sub_fields,
                    schema_types[target_type_name],
                    schema_types,
                    field_path,
                    method_name,
                )
                issues.extend(sub_issues)
            elif target_type_name:
                # Type referenced but not found in schema
                issues.append(
                    ValidationIssue(
                        method_name=method_name,
                        severity="WARNING",
                        message=(
                            f"Type '{target_type_name}' referenced by"
                            f" '{field_name}' not found in schema"
                        ),
                        field_path=field_path,
                    )
                )
        elif schema_field.type_kind == "OBJECT" and schema_field.type_name:
            # Field is an object type but no sub-selection was provided
            issues.append(
                ValidationIssue(
                    method_name=method_name,
                    severity="WARNING",
                    message=(
                        f"Field '{field_name}' is type '{schema_field.type_name}'"
                        f" (OBJECT) but has no sub-selection"
                    ),
                    field_path=field_path,
                )
            )

    return issues


def _similar(a: str, b: str) -> bool:
    """Check if two strings are similar (simple edit distance check)."""
    a_lower = a.lower()
    b_lower = b.lower()
    if a_lower == b_lower:
        return True
    if a_lower in b_lower or b_lower in a_lower:
        return True
    # Simple Levenshtein distance <= 2
    if abs(len(a) - len(b)) > 2:
        return False
    # Count common characters
    common = sum(1 for c in a_lower if c in b_lower)
    return common >= max(len(a), len(b)) - 2


def validate_queries(
    queries: list[ExtractedQuery],
    schema_types: dict[str, SchemaType],
) -> list[ValidationIssue]:
    """Validate all extracted queries against the schema."""
    all_issues: list[ValidationIssue] = []

    # Determine root types
    root_type_map = {
        "query": "Query",
        "mutation": "Mutation",
        "subscription": "Subscription",
    }

    for eq in queries:
        root_type_name = root_type_map.get(eq.operation_type)
        if not root_type_name or root_type_name not in schema_types:
            all_issues.append(
                ValidationIssue(
                    method_name=eq.method_name,
                    severity="WARNING",
                    message=(
                        f"Root type '{root_type_name}' not found in schema"
                        f" for operation type '{eq.operation_type}'"
                    ),
                    field_path=root_type_name or "UNKNOWN",
                )
            )
            continue

        root_type = schema_types[root_type_name]
        body = _extract_body(eq.query_string)
        fields = _parse_graphql_selection_set(body)
        issues = validate_selection(
            fields, root_type, schema_types, root_type_name, eq.method_name
        )
        all_issues.extend(issues)

    return all_issues


# =============================================================================
# SDL Schema Source (offline, or upstream for the server's API version)
# =============================================================================


_API_VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def normalise_api_version(api_version: str) -> str | None:
    """Return the upstream release tag (`v4.37.9`) for an API version, or None."""
    match = _API_VERSION_RE.match(api_version.strip())
    return f"v{match.group(1)}" if match else None


def fetch_upstream_schema(tag: str) -> GraphQLSchema:
    """Fetch the upstream generated SDL for a release tag."""
    return load_sdl(https_get(schema_url(tag)).decode("utf-8"))


def schema_types_from_graphql(schema: GraphQLSchema) -> dict[str, SchemaType]:
    """Adapt a graphql-core schema to the introspection-style type map."""
    types: dict[str, SchemaType] = {}
    for name, gql_type in schema.type_map.items():
        if name.startswith("__"):
            continue
        schema_type = SchemaType(name=name, kind=_kind_of(gql_type))
        for field_name, gql_field in getattr(gql_type, "fields", {}).items():
            named = get_named_type(gql_field.type)
            schema_type.fields[field_name] = SchemaField(
                name=field_name,
                type_name=named.name,
                type_kind=_kind_of(named),
                is_list=_has_list(gql_field.type),
                is_non_null=is_non_null_type(gql_field.type),
                args=list(getattr(gql_field, "args", {}) or {}),
            )
        if isinstance(gql_type, GraphQLEnumType):
            schema_type.enum_values = list(gql_type.values)
        types[name] = schema_type
    return types


def _kind_of(named: Any) -> str:
    if isinstance(named, GraphQLObjectType):
        return "OBJECT"
    if isinstance(named, GraphQLInterfaceType):
        return "INTERFACE"
    if isinstance(named, GraphQLInputObjectType):
        return "INPUT_OBJECT"
    if isinstance(named, GraphQLEnumType):
        return "ENUM"
    return type(named).__name__.removeprefix("GraphQL").removesuffix("Type").upper()


def _has_list(gql_type: Any) -> bool:
    while gql_type is not None:
        if is_list_type(gql_type):
            return True
        gql_type = getattr(gql_type, "of_type", None)
    return False


def validate_sdl(schema: GraphQLSchema) -> list[ValidationIssue]:
    """Validate the full library operation inventory with graphql.validate."""
    inventory = build_inventory(schema)
    print(f"  {len(inventory.operations)} unique operations in the inventory")
    return [
        ValidationIssue(
            method_name=", ".join(failure.methods),
            severity="ERROR",
            message=failure.message,
            field_path=", ".join(failure.locations),
        )
        for failure in validate_inventory(schema, inventory)
    ]


def inventory_as_queries() -> list[ExtractedQuery]:
    """The operation inventory in the shape the introspection validator uses."""
    return [
        ExtractedQuery(
            method_name=", ".join(op.methods),
            operation_type=op.operation_type,
            query_string=op.document,
            line_number=op.origins[0].line,
            path=op.origins[0].path,
        )
        for op in build_inventory().operations
    ]


def dump_schema(schema_types: dict[str, SchemaType]) -> None:
    """Write the schema type map to scripts/schema-dump.json."""
    dump_path = Path(__file__).resolve().parent / "schema-dump.json"
    dump_data = {}
    for type_name, st in sorted(schema_types.items()):
        dump_data[type_name] = {
            "kind": st.kind,
            "fields": {
                fn: {
                    "type": sf.type_name,
                    "kind": sf.type_kind,
                    "is_list": sf.is_list,
                    "is_non_null": sf.is_non_null,
                    "args": sf.args,
                }
                for fn, sf in sorted(st.fields.items())
            },
            "enum_values": st.enum_values,
        }
    dump_path.write_text(json.dumps(dump_data, indent=2))
    print(f"  Schema dumped to {dump_path}")


# =============================================================================
# Live Method Execution & Response Validation
# =============================================================================


@dataclass
class LiveTestResult:
    """Result of a live method test."""

    method_name: str
    status: str  # PASS, FAIL, SKIP, WARN
    message: str
    response_summary: str = ""


async def run_live_method_tests(client: UnraidClient) -> list[LiveTestResult]:
    """Run every client method and validate responses."""
    results: list[LiveTestResult] = []

    # Query methods that return raw dicts
    raw_methods: list[tuple[str, str]] = [
        ("test_connection", "Connection test"),
        ("get_version", "API version"),
        ("get_system_info", "System info"),
        ("get_registration", "Registration"),
        ("get_vars", "System vars"),
        ("get_owner", "Owner"),
        ("get_flash", "Flash info"),
        ("get_services", "Services"),
        ("get_array_status", "Array status"),
        ("get_array_disks", "Array disks"),
        ("get_shares", "Shares"),
        ("get_containers", "Containers"),
        ("get_docker_networks", "Docker networks"),
        ("get_vms", "VMs"),
        ("get_ups_status", "UPS status"),
        ("get_plugins", "Plugins"),
        ("get_notifications", "Notifications"),
        ("get_parity_history", "Parity history"),
        ("get_log_files", "Log files"),
        ("get_cloud", "Cloud"),
        ("get_connect", "Connect"),
        ("get_remote_access", "Remote access"),
        ("get_system_metrics", "System metrics"),
        ("get_metrics", "Raw metrics"),
    ]

    # Typed methods that return Pydantic models
    typed_methods: list[tuple[str, str]] = [
        ("typed_get_vars", "Typed vars"),
        ("typed_get_registration", "Typed registration"),
        ("typed_get_services", "Typed services"),
        ("typed_get_array", "Typed array"),
        ("typed_get_containers", "Typed containers"),
        ("typed_get_vms", "Typed VMs"),
        ("typed_get_ups_devices", "Typed UPS"),
        ("typed_get_shares", "Typed shares"),
        ("typed_get_flash", "Typed flash"),
        ("typed_get_owner", "Typed owner"),
        ("typed_get_plugins", "Typed plugins"),
        ("typed_get_docker_networks", "Typed networks"),
        ("typed_get_log_files", "Typed log files"),
        ("typed_get_cloud", "Typed cloud"),
        ("typed_get_connect", "Typed connect"),
        ("typed_get_remote_access", "Typed remote access"),
        ("typed_get_me", "Typed user account"),
        ("typed_get_api_keys", "Typed API keys"),
        ("get_notification_overview", "Notification overview"),
    ]

    # v4.30.0 methods
    v430_methods: list[tuple[str, str]] = [
        ("get_container_update_statuses", "Container updates"),
        ("get_ups_configuration", "UPS configuration"),
        ("get_display_settings", "Display settings"),
        ("get_docker_port_conflicts", "Port conflicts"),
    ]

    # v4.35.0+ / Unraid 7.3 methods
    v435_methods: list[tuple[str, str]] = [
        ("get_network_interfaces", "Network interfaces raw"),
        ("typed_get_network_interfaces", "Network interfaces typed"),
        ("get_docker_organizer", "Docker organizer raw"),
        ("typed_get_docker_organizer", "Docker organizer typed"),
        ("get_installed_unraid_plugins", "Installed plugins"),
        ("get_plugin_install_operations", "Plugin install operations"),
        ("get_servers", "Servers raw"),
        ("typed_get_servers", "Servers typed"),
        ("get_server", "Current server raw"),
        ("typed_get_server", "Current server typed"),
    ]

    all_methods = raw_methods + typed_methods + v430_methods + v435_methods

    for method_name, description in all_methods:
        method = getattr(client, method_name, None)
        if method is None:
            results.append(
                LiveTestResult(
                    method_name=method_name,
                    status="SKIP",
                    message="Method not found on client",
                )
            )
            continue

        try:
            result = await method()
            summary = _summarize_result(result)
            results.append(
                LiveTestResult(
                    method_name=method_name,
                    status="PASS",
                    message=description,
                    response_summary=summary,
                )
            )
        except Exception as e:
            results.append(
                LiveTestResult(
                    method_name=method_name,
                    status="FAIL",
                    message=f"{type(e).__name__}: {e}",
                )
            )

    return results


def _summarize_result(result: Any) -> str:
    """Create a brief summary of a method's return value."""
    if result is None:
        return "None"
    if isinstance(result, bool):
        return str(result)
    if isinstance(result, dict):
        keys = list(result.keys())[:5]
        return f"dict({len(result)} keys: {', '.join(keys)})"
    if isinstance(result, list):
        return f"list({len(result)} items)"
    type_name = type(result).__name__
    return f"{type_name}"


# =============================================================================
# Schema Diff — Compare Schema Types vs Pydantic Models
# =============================================================================


def compare_models_to_schema(
    schema_types: dict[str, SchemaType],
) -> list[ValidationIssue]:
    """Compare Pydantic models to GraphQL schema types to find drift."""
    import importlib

    models_module = importlib.import_module("unraid_api.models")
    issues: list[ValidationIssue] = []

    # Map Pydantic model names to likely GraphQL type names
    model_to_gql_type: dict[str, list[str]] = {
        "ArrayCapacity": ["ArrayCapacity"],
        "CapacityKilobytes": ["ArrayCapacityKilobytes", "CapacityKilobytes"],
        "ArrayDisk": [
            "UnraidArrayDisk",
            "ArrayDisk",
            "UnraidArrayBootDevice",
        ],
        "UnraidArray": ["UnraidArray"],
        "ParityCheck": [
            "ParityCheck",
            "ParityCheckStatus",
            "UnraidArrayParityCheckStatus",
        ],
        "DockerContainer": ["DockerContainer"],
        "VmDomain": ["VmDomain", "Domain"],
        "Share": ["Share", "UnraidShare"],
        "UPSDevice": ["UPSDevice", "Ups"],
        "UPSBattery": ["UPSBattery", "UpsBattery"],
        "UPSPower": ["UPSPower", "UpsPower"],
        "Vars": ["Vars"],
        "Registration": ["Registration"],
        "Service": ["Service"],
        "Flash": ["Flash"],
        "Owner": ["Owner"],
        "Plugin": ["Plugin"],
        "InfoNetworkInterface": ["InfoNetworkInterface", "NetworkInterface"],
        "ResolvedOrganizerV1": ["ResolvedOrganizerV1"],
        "ResolvedOrganizerView": ["ResolvedOrganizerView"],
        "Server": ["Server"],
        "ProfileModel": ["ProfileModel"],
        "PluginInstallOperation": ["PluginInstallOperation"],
        "PluginInstallEvent": ["PluginInstallEvent"],
    }

    for model_name, possible_gql_types in model_to_gql_type.items():
        model_class = getattr(models_module, model_name, None)
        if model_class is None:
            continue

        # Get Pydantic model fields
        try:
            model_fields = set(model_class.model_fields.keys())
        except AttributeError:
            continue

        # Find matching schema type
        matched_type = None
        for gql_name in possible_gql_types:
            if gql_name in schema_types:
                matched_type = schema_types[gql_name]
                break

        if matched_type is None:
            issues.append(
                ValidationIssue(
                    method_name="model_comparison",
                    severity="INFO",
                    message=(
                        f"Pydantic model '{model_name}' has no matching"
                        f" GraphQL type (tried: {', '.join(possible_gql_types)})"
                    ),
                    field_path=model_name,
                )
            )
            continue

        schema_fields = set(matched_type.fields.keys())

        # Fields in model but not in schema (may cause query failures)
        model_only = model_fields - schema_fields
        for f in sorted(model_only):
            # Skip computed properties and internal fields
            if f.startswith("_"):
                continue
            issues.append(
                ValidationIssue(
                    method_name="model_comparison",
                    severity="INFO",
                    message=(
                        f"Pydantic field '{model_name}.{f}' not found in"
                        f" GraphQL type '{matched_type.name}'"
                        f" (may be computed/aliased)"
                    ),
                    field_path=f"{model_name}.{f}",
                )
            )

        # Fields in schema but not in model (may be missing data)
        schema_only = schema_fields - model_fields
        for f in sorted(schema_only):
            issues.append(
                ValidationIssue(
                    method_name="model_comparison",
                    severity="INFO",
                    message=(
                        f"GraphQL field '{matched_type.name}.{f}' not in"
                        f" Pydantic model '{model_name}'"
                        f" (not queried by client)"
                    ),
                    field_path=f"{matched_type.name}.{f}",
                )
            )

    return issues


# =============================================================================
# Report Formatting
# =============================================================================


def print_schema_summary(schema_types: dict[str, SchemaType]) -> None:
    """Print a summary of the introspected schema."""
    print("\n" + "=" * 70)
    print("GRAPHQL SCHEMA SUMMARY")
    print("=" * 70)

    # Count by kind
    kinds: dict[str, int] = {}
    for t in schema_types.values():
        kinds[t.kind] = kinds.get(t.kind, 0) + 1

    for kind, count in sorted(kinds.items()):
        print(f"  {kind}: {count} types")

    # Show key types
    key_types = [
        "Query",
        "Mutation",
        "Subscription",
        "UnraidArray",
        "ArrayCapacity",
        "UnraidArrayDisk",
        "DockerContainer",
        "Share",
    ]
    print(f"\n{'─' * 70}")
    print("KEY TYPES:")
    for type_name in key_types:
        if type_name in schema_types:
            t = schema_types[type_name]
            fields = sorted(t.fields.keys())
            print(f"\n  {type_name} ({len(fields)} fields):")
            # Print fields in columns
            for j in range(0, len(fields), 4):
                row = fields[j : j + 4]
                print(f"    {', '.join(row)}")


def print_validation_report(
    query_issues: list[ValidationIssue],
    model_issues: list[ValidationIssue],
    live_results: list[LiveTestResult] | None,
) -> int:
    """Print the full validation report. Returns exit code."""
    exit_code = 0

    # Query validation (live server)
    print("\n" + "=" * 70)
    print("CLIENT QUERIES ↔ LIVE SERVER SCHEMA VALIDATION")
    print("=" * 70)

    errors = [i for i in query_issues if i.severity == "ERROR"]
    warnings = [i for i in query_issues if i.severity == "WARNING"]

    if not errors and not warnings:
        print("\n  ✅ All query fields match the server schema!")
    else:
        if errors:
            exit_code = 1
            print(f"\n  ❌ {len(errors)} ERROR(s) — fields NOT in schema:")
            for issue in errors:
                print(f"\n    [{issue.method_name}] {issue.field_path}")
                print(f"      {issue.message}")

        if warnings:
            print(f"\n  ⚠️  {len(warnings)} WARNING(s):")
            for issue in warnings:
                print(f"\n    [{issue.method_name}] {issue.field_path}")
                print(f"      {issue.message}")

    # Model comparison
    print("\n" + "=" * 70)
    print("PYDANTIC MODEL ↔ SCHEMA COMPARISON")
    print("=" * 70)

    info_issues = [i for i in model_issues if i.severity == "INFO"]
    model_errors = [i for i in model_issues if i.severity == "ERROR"]

    if model_errors:
        exit_code = 1
        print(f"\n  ❌ {len(model_errors)} ERROR(s):")
        for issue in model_errors:
            print(f"    {issue.message}")

    if info_issues:
        print(f"\n  ℹ️  {len(info_issues)} info note(s):")
        # Group by model name
        by_model: dict[str, list[str]] = {}
        for issue in info_issues:
            model = issue.field_path.split(".")[0]
            by_model.setdefault(model, []).append(issue.message)
        for model, msgs in sorted(by_model.items()):
            print(f"\n    {model}:")
            for msg in msgs:
                print(f"      • {msg}")
    else:
        print("\n  ✅ Models align with schema types!")

    # Live method results
    if live_results is not None:
        print("\n" + "=" * 70)
        print("LIVE METHOD EXECUTION")
        print("=" * 70)

        passed = sum(1 for r in live_results if r.status == "PASS")
        failed = sum(1 for r in live_results if r.status == "FAIL")
        skipped = sum(1 for r in live_results if r.status == "SKIP")

        for r in live_results:
            icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️", "WARN": "⚠️"}.get(
                r.status, "?"
            )
            line = f"  {icon} {r.method_name}"
            if r.response_summary:
                line += f" → {r.response_summary}"
            if r.status == "FAIL":
                line += f"\n       {r.message}"
            print(line)

        print(f"\n  Results: {passed} passed, {failed} failed, {skipped} skipped")
        if failed:
            exit_code = 1

    # Overall result
    print("\n" + "=" * 70)
    if exit_code == 0:
        print("✅ OVERALL: ALL VALIDATIONS PASSED")
    else:
        print("❌ OVERALL: ISSUES FOUND — See errors above")
    print("=" * 70)

    return exit_code


# =============================================================================
# Main
# =============================================================================


def load_schema_source(
    args: argparse.Namespace, api_version: str | None
) -> GraphQLSchema | None:
    """Load the SDL schema from --schema-file, or fetch the upstream release SDL.

    Returns None (after printing why) when no schema can be determined.
    """
    if args.schema_file:
        print(f"\n→ Loading schema from {args.schema_file}...")
        return load_sdl(Path(args.schema_file))
    version = args.api_version or api_version or "unknown"
    tag = normalise_api_version(version)
    if tag is None:
        print(
            f"ERROR: Cannot determine the upstream schema for API version {version!r}."
        )
        print("Pass --schema-file PATH or --api-version X.Y.Z.")
        return None
    print(f"\n→ Fetching upstream schema for unraid/api {tag}...")
    try:
        return fetch_upstream_schema(tag)
    except FetchError as err:
        print(f"ERROR: {err}")
        print("Pass --schema-file PATH or --api-version X.Y.Z.")
        return None


def run_schema_checks(
    schema: GraphQLSchema | None,
    schema_types: dict[str, SchemaType],
    args: argparse.Namespace,
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Dump/summarise the schema and validate the library against it."""
    print(f"  Found {len(schema_types)} types")
    if args.dump_schema:
        dump_schema(schema_types)
    print_schema_summary(schema_types)
    if schema is not None:
        print("\n→ Validating every library operation with graphql.validate...")
        query_issues = validate_sdl(schema)
    else:
        print("\n→ Extracting GraphQL operations from client source...")
        queries = inventory_as_queries()
        print(f"  {len(queries)} unique operations")
        print("\n→ Validating query fields against live schema...")
        query_issues = validate_queries(queries, schema_types)
    print("\n→ Comparing Pydantic models to schema types...")
    model_issues = compare_models_to_schema(schema_types)
    return query_issues, model_issues


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unraid API ↔ GraphQL Schema Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            This tool validates that the unraid-api client's GraphQL queries,
            mutations, and subscriptions match the Unraid API schema.

            By default the schema is the upstream SDL
            (api/generated-schema.graphql) for the server's API version.
            Unraid API 4.37.8+ refuses introspection, so --introspect only
            works on servers that still allow it.

            It catches issues like ha-unraid#196 where field renames or nesting
            changes break the client at runtime.

            examples:
              %(prog)s                  # Full validation (schema + live)
              %(prog)s --schema-only    # Validate queries against schema only
              %(prog)s --schema-file api.graphql --schema-only  # Offline
              %(prog)s --api-version 4.37.9 --schema-only       # No server
              %(prog)s --introspect     # Introspect the live server instead
              %(prog)s --live-only      # Run live method tests only
              %(prog)s --dump-schema    # Dump the schema type map to JSON
        """),
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Only load the schema and validate fields",
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Only run live method execution tests",
    )
    parser.add_argument(
        "--dump-schema",
        action="store_true",
        help="Dump the schema type map to schema-dump.json",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--schema-file",
        metavar="PATH",
        help="Validate against this SDL file; with --schema-only no server is needed",
    )
    source.add_argument(
        "--api-version",
        help="Fetch the upstream SDL for this API version instead of the server's",
    )
    source.add_argument(
        "--introspect",
        action="store_true",
        help="Introspect the live server (refused by Unraid API 4.37.8+)",
    )
    args = parser.parse_args()

    live_results: list[LiveTestResult] | None = None

    # === Offline: SDL only, no credentials or server ===
    if args.schema_only and (args.schema_file or args.api_version):
        schema = load_schema_source(args, None)
        if schema is None:
            return 1
        query_issues, model_issues = run_schema_checks(
            schema, schema_types_from_graphql(schema), args
        )
        return print_validation_report(query_issues, model_issues, live_results)

    # === Connect to live server ===
    host, api_key = load_env()
    print(f"\nHost: {_sanitize_host(host)}")
    print(f"API Key: {'*' * 8}...{'*' * 4} (loaded)")

    async with UnraidClient(host, api_key, verify_ssl=False) as client:
        # Get server version for context and the default schema source
        api_version: str | None = None
        try:
            ver = await client.get_version()
            api_version = ver.api
            print(f"Server: Unraid {ver.unraid}, API {ver.api}")
        except Exception as e:
            print(f"WARNING: Could not get server version: {e}")

        query_issues: list[ValidationIssue] = []
        model_issues: list[ValidationIssue] = []
        # --live-only discards schema results, so never let a missing or
        # unknown schema stop the live method tests.
        if not args.live_only:
            schema: GraphQLSchema | None = None
            if args.introspect:
                print("\n→ Introspecting live GraphQL schema...")
                schema_types = await introspect_schema(client)
            else:
                schema = load_schema_source(args, api_version)
                if schema is None:
                    return 1
                schema_types = schema_types_from_graphql(schema)

            query_issues, model_issues = run_schema_checks(
                schema, schema_types, args
            )

        if not args.schema_only:
            # Run live method tests
            print("\n→ Running live method tests...")
            live_results = await run_live_method_tests(client)

    return print_validation_report(query_issues, model_issues, live_results)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
