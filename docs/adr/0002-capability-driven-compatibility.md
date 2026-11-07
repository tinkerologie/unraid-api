# Adapt operations to server capabilities

The client uses GraphQL introspection to find the fields that the server supports.
It keeps the result in a cache for the life of the client.
It uses the result to select fields and prevent requests that the server does not support.

If the server returns `INTROSPECTION_DISABLED`, the client uses the current field set and omits obsolete fields.
For other introspection failures, the client permits requests without a list of supported fields.
If authentication fails, the client raises `UnraidAuthenticationError`.

The client can operate when introspection is not available.
In that case, an operation can fail if the server does not support the requested field.
The standby check uses a separate API version check.

## Related files

- [capability representation](../../src/unraid_api/capabilities.py)
- [discovery and guards](../../src/unraid_api/client.py)
- [capability tests](../../tests/test_capabilities.py)
- [disabled-introspection tests](../../tests/test_api_4378_compat.py)
- [ADR 0004](0004-standby-aware-reads.md)
