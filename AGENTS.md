# AI Agent Instructions for Unraid API Python Library

> Single source of truth for all AI coding assistants working on this repository.

## Project Identity

| Key | Value |
| --- | --- |
| **Name** | Unraid API Python Library |
| **Repository** | `github.com/tinkerologie/unraid-api` |
| **Default Branch** | `main` |
| **Description** | Python client library and CLI for the Unraid GraphQL API. |
| **Primary Consumer** | The [ha-unraid](https://github.com/tinkerologie/ha-unraid) Home Assistant integration |

Use [ASD-STE100 Issue 9](docs/agents/documentation.md) for new or changed English documentation.

## Mandatory Development Workflow for AI Agents

All AI coding agents must follow these steps.

1. Find the GitHub issue before you write code or create a pull request (PR).
2. Use the official issue form. Use `01-bug-report.yml` for a bug or `02-enhancement-request.yml` for an enhancement.
3. Make sure the issue has a CodeRabbit Coding Plan (`@coderabbitai plan`). Read the approved plan. Follow it.
4. Create a branch for the issue. Use `feat/<issue-id>-<description>` or `fix/<issue-id>-<description>`. Do not commit to `main`.
5. Record user-facing or architecture changes under `## [Unreleased]` in `CHANGELOG.md`.
6. Run all local test, lint, format, and type checks before you commit. Correct all errors and warnings.
7. Use `.github/PULL_REQUEST_TEMPLATE.md`. Complete each field. Link the issue as specified in **Issue and Pull Request Governance**. Complete the Pre-Submission Governance checklist. Paste the terminal output from the checks.
8. Open the PR as a draft (`gh pr create --draft`).
9. Wait for all CI checks on the draft PR to pass.
10. Complete the required verification. Then mark the PR as ready for review (`gh pr ready`).
11. Review and resolve all CodeRabbit and GitHub Copilot comments. Check that Codecov shows zero errors, zero warnings, and no decrease in coverage.


## Executable Verification Commands

- `pytest` — Run test suite
- `pytest --cov=src` — Run tests with coverage
- `ruff check .` — Run ruff linter
- `ruff format --check .` — Check code formatting
- `mypy src script` — Static type checking
- `pre-commit run --all-files` — Run all configured pre-commit hooks

`script/` holds the repository tooling (`schema_tools.py`, `upstream_watch.py`). Unlike
`scripts/`, it is linted, type-checked and covered by tests like the library.

Use `uv` to manage dependencies. Run the tools above with `uv run`, for example
`uv run pytest`. The pre-commit hooks run ruff, mypy and security checks.

```bash
uv sync --all-extras                                                     # Setup
uv run pytest tests/ -v --cov=src/unraid_api                             # All tests with coverage
uv run pytest tests/test_client.py -v                                    # Single test file
uv run pytest tests/test_client.py::TestClassName::test_method_name -v   # Single test
uv run ruff format .                                                     # Format
```

## Architecture

```text
src/unraid_api/
├── __init__.py      # Public exports, version
├── client.py        # UnraidClient - async GraphQL client with SSL auto-discovery
├── models.py        # Pydantic response models (UnraidBaseModel ignores unknown fields)
└── exceptions.py    # UnraidAPIError hierarchy (Connection, Auth, Timeout)
```

See `UNRAIDAPI.md` for available GraphQL fields and schema documentation.

### Client Design

- **Async context manager**: `async with UnraidClient(host, api_key) as client:`
- **Session injection**: Accepts external `aiohttp.ClientSession` for HA integration (will not be closed by client)
- **SSL auto-discovery**: Handles Unraid's "No", "Yes", and "Strict" SSL modes through redirect detection
- **GraphQL variables**: Always use variables, never string interpolation for security

### Key Patterns

**GraphQL mutations use PrefixedID type:**

```python
mutation = """
    mutation StartContainer($id: PrefixedID!) {
        docker { start(id: $id) { id state } }
    }
"""
await self.mutate(mutation, {"id": container_id})
```

**Pydantic models extend UnraidBaseModel for forward compatibility:**

```python
class ArrayDisk(UnraidBaseModel):
    id: str
    name: str | None = None
```

### Disk Standby Awareness

- `get_array_status()` and `get_array_disks()` do NOT wake sleeping disks (safe for polling)
- `get_physical_disks()` WILL wake sleeping disks (use sparingly)
- Check the `isSpinning` field. For disks in standby, `temp` is null or zero.

## Test Requirements

- TDD: Write tests first
- Use `pytest-asyncio` with `asyncio_mode = "auto"`
- Mock fixtures in `tests/conftest.py`

## Boundaries and Safety Constraints

- Always: Write tests for any new or modified functionality, verify changes locally, and update CHANGELOG.md under `[Unreleased]`.
- Ask first: Major architectural changes, removing public APIs, or adding heavy external dependencies.
- Never: Commit secrets, credentials, API keys, or private certificates. Do not commit directly to `main`.

## Working Principles

### Think Before Coding

**Do not assume. Do not hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - do not pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If an instruction is unclear, stop. Identify the instruction. Ask for clarification.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that was not requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Do not "improve" adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Use the style of the existing code.
- If you notice unrelated dead code, mention it - do not delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Do not remove pre-existing dead code unless asked.

The test: Each changed line should trace directly to the user's request.

### Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Run the tests before the change. Run them again after the change."

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Issue and Pull Request Governance

These rules apply to each contributor, including AI coding agents. The full org-wide rules are in
[GOVERNANCE.md](https://github.com/tinkerologie/.github/blob/main/GOVERNANCE.md).

1. **Issue first.** Open an issue with the bug or enhancement template before you open a pull
   request. Use `[Bug]:` or `[Enhancement]:`, followed by a space and the title.
   The labeler adds `bug` or `enhancement` when it can identify the issue type.
   CodeRabbit then adds a Coding Plan to the issue. Follow that plan.
   The labeler skips issues with `question`, `duplicate`, `invalid`, `wontfix`, or `no-type`.
   It does not add a type label again if a maintainer removed it.
2. **Link the issue.** In **Related Issues**, use `Closes #<number>`, `Fixes #<number>`, or
   `Resolves #<number>` if the PR completes the issue. GitHub then closes the issue when
   the PR merges. For partial work, use `Part of #<number>` or `Related to #<number>`.
   Link to an existing issue. You can link to an issue in another public repository
   with `owner/repo#123`. Only contributors with write access or higher can use
   `None` for maintenance work such as CI, documentation, or dependency updates.
3. **One change at a time.** GitHub limits contributors without write access to two open,
   non-draft pull requests. Draft pull requests do not count. Do not edit files that another
   open PR changes. Examples include `CHANGELOG.md`, translations, `README.md`, and generated
   bundles. Wait for the first PR to merge. Then rebase your branch before you continue.
4. **Act on the Tinkerologie-Bot report.** If the PR governance check fails, the bot lists
   all problems in one numbered comment. Correct each problem in the PR description
   or push the necessary change. The check runs again and the bot updates the comment.
5. **Rebase before review.** Rebase on `main` before you mark the PR ready for review.
6. **Resolve conflicts first.** If the PR has the `conflicts` label, rebase on `main`.
   Resolve the conflicts. Keep all `CHANGELOG.md` entries under `[Unreleased]`.
   Run the tests again. Force-push the branch before you do other work.
7. **Coverage.** Tests must cover at least 90% of the added or changed lines for
   `codecov/patch`. Add tests for uncovered lines in the Codecov comment.
   In the PR description, explain each line that still has no coverage.
   Do not decrease coverage targets or add coverage ignore rules to pass the check.
8. **Stale items.** The bot adds `stale` to issues and PRs after 14 days without activity.
   It closes them 30 days later if there is no new activity. The bot skips these labels.
   - Issues: `pinned`, `security`, `confirmed`, `work-in-progress`, `priority: critical`, `priority: high`.
   - Pull requests: `pinned`, `security`, `work-in-progress`.
