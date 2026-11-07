# Keep transport lifecycle in the asynchronous client

`UnraidClient` sends GraphQL requests over HTTP.
The client finds the endpoint and SSL mode.
It also manages the WebSocket protocol.

The client can open and close its own HTTP session.
It can also use a session from the caller.
When the caller supplies a session, the caller closes it.
This lets Home Assistant keep control of its session.

Each subscription generator manages its WebSocket connection.
If the stream fails, the caller can reconnect.
The application sets its own update intervals and decides when to reconnect.
Queries and subscriptions share one endpoint and session for each client.

## Related files

- [client lifecycle and subscriptions](../../src/unraid_api/client.py)
- [session tests](../../tests/test_client_async.py)
- [subscription tests](../../tests/test_subscriptions.py)
- [public usage](../../README.md)
