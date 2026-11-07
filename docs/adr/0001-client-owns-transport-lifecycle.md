# Keep transport lifecycle in the asynchronous client

`UnraidClient` owns GraphQL HTTP execution, SSL-mode and endpoint discovery, and
WebSocket protocol handling. It can create and close its own asynchronous session
or borrow a caller-supplied session without closing it, allowing Home Assistant to
retain session ownership; subscription generators manage their WebSocket lifetime
and surface stream failures for callers to reconnect. This gives consumers one
client interface while leaving application refresh schedules and reconnect policy
outside the library, at the cost of shared session and resolved-endpoint state
inside each client.

See [client lifecycle and subscriptions](../../src/unraid_api/client.py),
[session tests](../../tests/test_client_async.py),
[subscription tests](../../tests/test_subscriptions.py), and
[public usage](../../README.md). This is a retrospective description of the
implemented ownership contract.
