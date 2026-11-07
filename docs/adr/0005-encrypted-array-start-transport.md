# Require verified HTTPS for array decryption credentials

Starting an encrypted array sends decryption values as GraphQL variables only
over verified HTTPS bound to the configured hostname and port. This path bypasses
ordinary plaintext endpoint discovery, rejects disabled certificate verification
and redirects to a different authority, and supplies verified TLS even with a
borrowed session; it does not replace the ordinary request’s resolved-URL cache.
This intentionally requires callers to configure the canonical trusted HTTPS
endpoint instead of relying on the convenience discovery used by ordinary reads,
so array decryption credentials cannot follow a downgrade or cross-server redirect.

See [encrypted start and request handling](../../src/unraid_api/client.py),
[transport regression tests](../../tests/test_client_async.py), and
[encrypted-array guidance](../../README.md). Ordinary reads retain their existing
SSL-mode discovery behavior; this ADR does not claim all client operations require
HTTPS.
