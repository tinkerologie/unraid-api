"""Tests for ServerCapabilities introspection-based feature detection."""

from __future__ import annotations

import pytest

from unraid_api.capabilities import ServerCapabilities


@pytest.fixture
def sample_introspection() -> dict[str, object]:
    """Realistic aliased __type introspection response."""
    return {
        "Query": {
            "name": "Query",
            "fields": [
                {"name": "array"},
                {"name": "docker"},
                {"name": "network"},
                {"name": "info"},
            ],
        },
        "Mutation": {
            "name": "Mutation",
            "fields": [
                {"name": "createNotification"},
                {"name": "notifyIfUnique"},
                {"name": "updateTemperatureConfig"},
            ],
        },
        "Subscription": {
            "name": "Subscription",
            "fields": [
                {"name": "notificationAdded"},
                {"name": "notificationsOverview"},
                {"name": "parityHistorySubscription"},
            ],
        },
        "DockerContainer": {
            "name": "DockerContainer",
            "fields": [
                {"name": "id"},
                {"name": "names"},
                {"name": "labels"},
                {"name": "mounts"},
                {"name": "networkSettings"},
                {"name": "tailscaleStatus"},
            ],
        },
        "TailscaleStatus": {
            "name": "TailscaleStatus",
            "fields": [
                {"name": "online"},
                {"name": "version"},
                {"name": "exitNodeStatus"},
                {"name": "tailscaleIps"},
            ],
        },
    }


class TestServerCapabilitiesHas:
    """Test dotted-path feature lookup."""

    def test_has_returns_true_for_known_query_field(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has("Query.network") is True

    def test_has_returns_false_for_missing_query_field(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has("Query.nonexistentField") is False

    def test_has_returns_true_for_mutation(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has("Mutation.updateTemperatureConfig") is True

    def test_has_returns_true_for_subscription(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has("Subscription.notificationAdded") is True

    def test_has_returns_true_for_nested_type_field(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has("DockerContainer.labels") is True
        assert caps.has("TailscaleStatus.exitNodeStatus") is True

    def test_has_returns_false_for_unknown_type(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has("SomeUnknownType.field") is False

    def test_has_raises_on_malformed_path(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        with pytest.raises(ValueError, match="dotted"):
            caps.has("notDotted")


class TestServerCapabilitiesHasAllAny:
    def test_has_all_true_when_every_path_present(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has_all("Query.network", "Mutation.createNotification") is True

    def test_has_all_false_when_one_missing(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has_all("Query.network", "Query.missing") is False

    def test_has_any_true_when_one_present(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has_any("Query.missing", "Query.network") is True

    def test_has_any_false_when_all_missing(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.has_any("Query.missing", "Query.alsoMissing") is False


class TestServerCapabilitiesPermissive:
    def test_permissive_returns_true_for_anything(self) -> None:
        caps = ServerCapabilities.permissive()
        assert caps.has("Query.anything") is True
        assert caps.has("SomeType.madeUpField") is True
        assert caps.has_all("A.b", "C.d") is True

    def test_permissive_is_flagged(self) -> None:
        caps = ServerCapabilities.permissive()
        assert caps.is_permissive is True

    def test_from_introspection_is_not_permissive(
        self, sample_introspection: dict[str, object]
    ) -> None:
        caps = ServerCapabilities.from_introspection_response(sample_introspection)
        assert caps.is_permissive is False


class TestServerCapabilitiesFromIntrospection:
    def test_handles_null_type_entry(self) -> None:
        """A missing type in the server schema returns null from __type."""
        caps = ServerCapabilities.from_introspection_response(
            {
                "Query": {
                    "name": "Query",
                    "fields": [{"name": "array"}],
                },
                "Subscription": None,
            }
        )
        assert caps.has("Query.array") is True
        assert caps.has("Subscription.anything") is False

    def test_handles_empty_response(self) -> None:
        caps = ServerCapabilities.from_introspection_response({})
        assert caps.has("Query.array") is False
        assert caps.is_permissive is False


def test_install_and_vm_capability_types() -> None:
    """Introspection includes the optional install mutations and VM UUID."""
    from unraid_api.capabilities import CAPABILITY_TYPES, build_introspection_query

    query = build_introspection_query()
    for name in ("UnraidPluginsMutations", "VmDomain"):
        assert name in CAPABILITY_TYPES
        assert f'{name}: __type(name: "{name}")' in query
