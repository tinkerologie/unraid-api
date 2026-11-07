# Adapt operations to server capabilities

The client discovers relevant GraphQL fields once per client using introspection
and composes or guards operations from that cached result instead of assuming
that every supported server has the same schema. Explicit `INTROSPECTION_DISABLED`
responses select the known-current field set minus retired fields; other
introspection failures use a permissive fallback, while authentication failures
propagate. This preserves access when introspection is unavailable, trading exact
feature knowledge for possible operation-time errors and a cache that lasts for
the client’s lifetime.

See [capability representation](../../src/unraid_api/capabilities.py),
[discovery and guards](../../src/unraid_api/client.py),
[capability tests](../../tests/test_capabilities.py), and
[disabled-introspection tests](../../tests/test_api_4378_compat.py).
Standby-sensitive reads have a separate version gate in [ADR 0004](0004-standby-aware-reads.md).
