# Expose explicit read variants for standby-sensitive polling

The library exposes temperature-free system metrics and lightweight container
inventory reads alongside fuller reads, so polling consumers can avoid temperature
resolvers that wake disks and Docker writable-layer size calculations. Temperature
collection is considered standby-safe only for API versions at least 4.37.6;
unknown versions fail closed, and that guarantee does not extend to physical-disk
queries. The trade-off is an explicit choice of read method and potentially less
telemetry, rather than hiding expensive or disk-waking work behind every metrics
request.

See [read methods and support check](../../src/unraid_api/client.py),
[threshold](../../src/unraid_api/const.py),
[read regression tests](../../tests/test_client_async.py), and
[consumer guidance](../../README.md). API and OS versions are distinct; the
standby check uses the API version only.
