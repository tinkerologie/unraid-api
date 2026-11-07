# Copilot Instructions for unraid-api

## Project Overview

`unraid-api` is an async Python client library (PyPI package) for Unraid's official GraphQL API. It supports API v4.21.0+ and Unraid 7.1.4+. Its primary consumer is the [ha-unraid](https://github.com/ruaan-deysel/ha-unraid) Home Assistant integration.

## Critical Requirements

### Test-Driven Development (TDD)
- **Each feature MUST have tests written FIRST** before implementation
- Test files live in `tests/` directory, mirroring source structure
- Use `pytest` with `pytest-asyncio` for async tests
- Run tests: `pytest tests/ -v --cov=src/unraid_api`
- Minimum coverage target: 80%

### Zero Tolerance for Linting
- **No linting warnings or errors allowed**
- Tools: `ruff` for linting/formatting, `mypy` for type checking
- Run before committing: `ruff check . && ruff format --check . && mypy src/`
- All functions must have type hints

### Security Requirements
- **Never hardcode credentials** - use environment variables or secure config
- **Never log sensitive data** (API keys, passwords, tokens)
- Use GraphQL variables for all parameters (never string interpolation)
- Validate all user inputs before use
- Keep dependencies updated for security patches

## Architecture

```
unraid-api/
├── src/unraid_api/          # Package source
│   ├── __init__.py          # Public exports
│   ├── client.py            # UnraidClient async class
│   ├── models.py            # Pydantic response models
│   ├── exceptions.py        # Custom exception hierarchy
│   └── py.typed             # PEP 561 marker
├── tests/                   # Test files
│   ├── conftest.py          # Shared fixtures
│   ├── test_client.py       # Client tests
│   ├── test_models.py       # Model tests
│   └── test_exceptions.py   # Exception tests
├── pyproject.toml           # Package config, all tool settings
└── UNRAIDAPI.md             # GraphQL schema reference
```

### Client Design Pattern
- **Async-first**: Uses `aiohttp` for all HTTP operations
- **Context manager**: `async with UnraidClient(...) as client:`
- **Queries** → `get_*` methods or direct `query()` calls
- **Mutations** → action methods (`start_*`, `stop_*`) or `mutate()` calls
- **Session injection**: Accepts external `aiohttp.ClientSession` for HA integration

### Exception Hierarchy
```
UnraidAPIError (base)
├── UnraidConnectionError   # Network failures
├── UnraidAuthenticationError  # Invalid API key
└── UnraidTimeoutError      # Request timeout
```

## Code Conventions

### GraphQL with Variables (Security Pattern)
Always use GraphQL variables - never string interpolation:
```python
async def start_container(self, container_id: str) -> dict[str, Any]:
    """Start a Docker container."""
    mutation = """
        mutation StartContainer($id: PrefixedID!) {
            docker {
                start(id: $id) { id state }
            }
        }
    """
    return await self.mutate(mutation, {"id": container_id})
```

### Pydantic Models
Use `UnraidBaseModel` for forward compatibility (ignores unknown fields):
```python
class ArrayDisk(UnraidBaseModel):
    id: str
    name: str | None = None
    temp: int | None = None
```

### Test Pattern
```python
class TestClientInitialization:
    def test_init_with_required_params(self, host: str, api_key: str) -> None:
        """Test client initialization with required parameters."""
        client = UnraidClient(host, api_key)
        assert client.host == host
```

## Developer Workflow

### Setup
```bash
# Install dependencies with uv
uv sync --all-extras
```

### Pre-commit Checklist
```bash
uv run pytest tests/ -v --cov=src/unraid_api
uv run ruff check .
uv run ruff format .
uv run mypy src/
```

**Pre-commit MUST always be run before any commit.**

### Usage Example
```python
from unraid_api import UnraidClient

async with UnraidClient("192.168.1.100", "your-api-key") as client:
    if await client.test_connection():
        version = await client.get_version()
        print(f"Unraid {version['unraid']}, API {version['api']}")
```

## Adding New Features

1. **Write tests first** in `tests/` for the new functionality
2. Add method to `client.py` following async patterns
3. Add Pydantic models to `models.py` if needed
4. Use GraphQL variables for all parameters
5. Add type hints to all parameters and return values
6. Reference `UNRAIDAPI.md` for available GraphQL fields
7. Run full lint/test suite before committing
8. **Update documentation** (see Documentation Requirements below)
9. **Update version numbers** (see Versioning below)

## Documentation Requirements

**README.md and CHANGELOG.md MUST always be kept up to date.**

### README.md
- Update API Reference tables when adding new methods
- Update Models section when adding new Pydantic models
- Keep usage examples current and working

### CHANGELOG.md
- Follow [Keep a Changelog](https://keepachangelog.com) format
- Add entries under `[Unreleased]` section during development
- Categories: Added, Changed, Deprecated, Removed, Fixed, Security
- Move entries to versioned section on release

## Versioning

**Version numbers MUST be updated when new features or bug fixes are made.**

### Semantic Versioning
- **MAJOR** (X.0.0): Breaking API changes
- **MINOR** (0.X.0): New features, backward compatible
- **PATCH** (0.0.X): Bug fixes, backward compatible

### Version Locations (update ALL)
1. `pyproject.toml` → `version = "X.Y.Z"`
2. `src/unraid_api/__init__.py` → `__version__ = "X.Y.Z"`

### When to Bump
- **New methods/models**: MINOR version bump
- **Bug fixes**: PATCH version bump
- **Breaking changes**: MAJOR version bump (rare)

## Live API Testing

A unified test script at `scripts/unraid-api-client.py` tests the library against a real Unraid server.

### Credentials
Create `scripts/.env` with:
```
IP: 192.168.x.x
API Key: your-api-key-here
```
Environment variables `UNRAID_HOST` and `UNRAID_API_KEY` override the `.env` file.

### Running Tests
```bash
# Query tests (54 read-only tests covering all methods)
python scripts/unraid-api-client.py

# WebSocket subscription tests (7 tests)
python scripts/unraid-api-client.py --subscriptions

# SSL detection tests
python scripts/unraid-api-client.py --ssl

# Run everything
python scripts/unraid-api-client.py --all
```

### Test Suites
- **Query tests** cover these areas.
  - Connection, version, compatibility, system info, registration, vars, and metrics
  - Owner, flash, services, array, disks, shares, and parity history
  - Containers, networks, VMs, UPS, plugins, notifications, and logs
  - Cloud, Connect, remote access, user account, and API keys
  - All typed methods and v4.30.0 features
- **Subscription tests**: CPU metrics, memory metrics, CPU telemetry, array updates, UPS updates, container stats, raw subscribe
- **SSL tests**: Standard ports, same-port (ha-unraid behavior), nginx 400 detection, HTTP-as-single-port

## Dependencies

Core: `aiohttp>=3.9.0`, `pydantic>=2.0.0`
Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `aiointercept`, `ruff`, `mypy`

### Dependency Notes

**aiointercept (test mocking)**. Use `aiointercept` (https://github.com/Polandia94/aiointercept) to mock aiohttp requests.
It patches the DNS resolver to send requests to a local aiohttp.web test server.
The old `aioresponses` library does not support the `ClientResponse.__init__()` change in aiohttp 3.14.0.
The change to `aiointercept` removed the `aiohttp<3.14.0` constraint.
- Test URLs must use hostnames (for example `unraid.test`), never bare IPs — DNS patching cannot intercept IP literals.
- Use `async with aiointercept(mock_external_urls=True) as m:` (async context manager).
- `exception=True` closes the connection so the client sees `ClientConnectionError`. Tests that need a specific exception type (TimeoutError, SSL errors, ClientResponseError) patch the client session directly with `unittest.mock.patch.object(client._session, "post", side_effect=...)`.
