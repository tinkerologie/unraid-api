# Expose explicit read variants for standby-sensitive polling

The library has a system metrics query that omits temperatures.
It also has a Docker inventory query that omits writable-layer sizes and other fields.
These queries prevent disk spin-up from temperature requests and reduce Docker work during polls.

The library reports temperature queries as safe for standby if the API version is 4.37.6 or later.
If the library cannot read the API version, it does not report temperature queries as safe.
The standby check does not apply to physical disk queries.

Callers select the query that supplies the necessary data.
Queries that use fewer fields can return less data.
The standby check uses the API version independently of the Unraid OS version.

## Related files

- [read methods and support check](../../src/unraid_api/client.py)
- [threshold](../../src/unraid_api/const.py)
- [read regression tests](../../tests/test_client_async.py)
- [consumer guidance](../../README.md)
