# Normalize server data while preserving meaningful query failures

Domain-facing readers return Pydantic models whose base configuration ignores
unknown fields, allowing additive server changes without forcing consumers to
parse new response fields; existing raw readers and generic query/mutation methods
remain available for compatibility. GraphQL responses with errors and at least
one non-null root return the partial data, whereas responses with errors and no
usable root raise a library exception. Ordinary query failures retain structured
errors; complete authorization failures are classified separately as authentication
exceptions without retaining the structured error list. This keeps useful optional data while
requiring resource readers to handle nullable roots and consumers to distinguish
query failure from a genuinely empty inventory.

See [base model](../../src/unraid_api/models.py),
[query classification and resource readers](../../src/unraid_api/client.py),
[model tests](../../tests/test_models.py), and
[nullable-root and partial-result tests](../../tests/test_api_4378_compat.py).
This describes the current contract, not a guarantee that every possible partial
nested response is normalized identically.
