# Require verified HTTPS for array decryption credentials

The client sends array decryption credentials as GraphQL variables over HTTPS.
It verifies the server certificate, also when the caller supplies the HTTP session.
It sends the credentials to the hostname and port from the client configuration.

The client rejects an encrypted start if certificate verification is off.
It also rejects a redirect to a different hostname, port, or protocol.
It does not use plaintext endpoint discovery or change the endpoint in the cache for ordinary requests.

Set the hostname and HTTPS port for the endpoint that has the correct certificate.
Ordinary reads continue to use SSL mode discovery.

## Related files

- [encrypted start and request handling](../../src/unraid_api/client.py)
- [transport regression tests](../../tests/test_client_async.py)
- [encrypted-array guidance](../../README.md)
