"""Server capability detection via GraphQL introspection.

Detects which fields, types, mutations, and subscriptions a particular Unraid
server supports so the client can compose queries that match what that server
exposes. This lets the library target multiple Unraid API versions from a
single codebase without breaking on older servers that lack newer fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

CAPABILITY_TYPES: tuple[str, ...] = (
    "Query",
    "Mutation",
    "Subscription",
    "DockerContainer",
    "TailscaleStatus",
    "DockerNetwork",
    "Notification",
    "ParityCheck",
    "UnraidArray",
    "Metrics",
    "DockerMutations",
    "ArrayMutations",
    "InfoNetworkInterface",
    "ResolvedOrganizerV1",
    "Server",
    "PluginInstallOperation",
    "UnraidPluginsMutations",
    "VmDomain",
)


def build_introspection_query() -> str:
    """Single aliased __type query covering every capability-relevant type."""
    fragments = "\n".join(
        f'    {type_name}: __type(name: "{type_name}") {{ name fields {{ name }} }}'
        for type_name in CAPABILITY_TYPES
    )
    return "query ServerCapabilities {\n" + fragments + "\n        }"


class ServerCapabilities:
    """Typed view over which GraphQL fields a specific server exposes."""

    __slots__ = ("_fields", "_permissive")

    def __init__(
        self,
        fields: Mapping[str, frozenset[str]],
        *,
        permissive: bool = False,
    ) -> None:
        self._fields: dict[str, frozenset[str]] = dict(fields)
        self._permissive = permissive

    @property
    def is_permissive(self) -> bool:
        return self._permissive

    @classmethod
    def permissive(cls) -> ServerCapabilities:
        """Fallback when introspection fails — assume every feature is present."""
        return cls({}, permissive=True)

    @classmethod
    def from_introspection_response(
        cls, response: Mapping[str, Any]
    ) -> ServerCapabilities:
        """Parse the aliased `__type` response into a capability map."""
        fields: dict[str, frozenset[str]] = {}
        for type_name, type_entry in response.items():
            if not type_entry:
                continue
            type_fields = type_entry.get("fields") or []
            fields[type_name] = frozenset(
                f["name"] for f in type_fields if isinstance(f, dict) and "name" in f
            )
        return cls(fields)

    def has(self, path: str) -> bool:
        """Check whether a dotted path (`TypeName.fieldName`) exists on the server."""
        if self._permissive:
            return True
        if "." not in path:
            raise ValueError(
                f"Capability path must be dotted (TypeName.fieldName), got {path!r}"
            )
        type_name, field_name = path.split(".", 1)
        type_fields = self._fields.get(type_name)
        if type_fields is None:
            return False
        return field_name in type_fields

    def has_all(self, *paths: str) -> bool:
        return all(self.has(p) for p in paths)

    def has_any(self, *paths: str) -> bool:
        return any(self.has(p) for p in paths)
