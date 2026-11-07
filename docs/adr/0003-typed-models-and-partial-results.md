# Normalize server data while preserving meaningful query failures

Typed readers return Pydantic models.
The models ignore fields that they do not recognize.
If the server adds fields, existing callers can continue to use the models.
Callers can also use the raw readers and the generic query and mutation methods.

If a GraphQL response has errors and at least one root value, the client returns the available data.
If the response has errors and no root value, the client raises a library exception.
For ordinary query errors, the exception contains the structured errors.
For a complete authorization failure, the client raises an authentication exception.
The authentication exception does not contain the structured error list.

Readers must handle null root values.
A failed query and a successful query with an empty inventory have different meanings.
Nested values in partial responses can have different rules.

## Related files

- [base model](../../src/unraid_api/models.py)
- [query classification and resource readers](../../src/unraid_api/client.py)
- [model tests](../../tests/test_models.py)
- [nullable-root and partial-result tests](../../tests/test_api_4378_compat.py)
