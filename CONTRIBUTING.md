# Contributing to Unraid API Python Library

Use [ASD-STE100 Issue 9](docs/agents/documentation.md) for new or changed English documentation.

Thank you for your interest in contributing to Unraid API Python Library. This project welcomes contributions from human developers and autonomous AI coding agents alike.

This project supplies a Python client and CLI for the Unraid GraphQL API. The client uses HTTP for queries and mutations. It uses WebSocket for subscriptions.

All contributors must follow this workflow. It helps maintainers review changes and maintain code quality.

---

## Code of Conduct and Standards

- Be respectful, constructive, and collaborative.
- Zero secrets policy: Do not commit passwords, tokens, API keys, private certificates, or personal data.
- Anti-burnout principle: Perform full due diligence locally before opening pull requests or requesting review.

---

## Development Workflow

All contributors and AI agents must follow these steps.

### 1. Open a GitHub Issue First
- Each bug fix, feature, or enhancement must start with an issue.
- Use the appropriate GitHub Issue Form:
  - Bug Report (`01-bug-report.yml`)
  - Enhancement Request (`02-enhancement-request.yml`)
- GitHub accepts issues from the issue forms. Maintainers close pull requests that have no issue.

### 2. CodeRabbit AI Plan Generation
- CodeRabbit can make a plan when GitHub adds the `bug` or `enhancement` label. To start it manually, add the comment `@coderabbitai plan` to the issue.
- CodeRabbit examines the code and posts a Coding Plan. The plan includes these items.
  - Codebase research and affected components
  - Architectural design choices
  - Phased task breakdowns
  - Machine-readable agent prompts and verifiable acceptance criteria
- Contributors must review, refine, and confirm the plan before writing code. Do not start implementation without an approved plan.

### 3. Create a Dedicated Branch
- Create a feature or bugfix branch off `main`:
  - Features: `git checkout -b feat/<issue-number>-<short-description>`
  - Fixes: `git checkout -b fix/<issue-number>-<short-description>`
  - Documentation: `git checkout -b docs/<issue-number>-<short-description>`
- Do not commit directly to the default branch (`main`).

### 4. Implementation and Local Validation
- Implement changes following project conventions and the approved plan.
- Update `CHANGELOG.md` under `## [Unreleased]` describing what changed and why.
- Run all required local validation checks (tests with coverage, linters, type checkers, and formatters). Correct all errors and warnings.

### 5. Follow the Pull Request Template
- Open a Pull Request using `.github/PULL_REQUEST_TEMPLATE.md`.
- Complete all sections in the template:
  - Summary of changes
  - Linked issue keywords (`Fixes #<issue>`, `Closes #<issue>`, `Addresses #<issue>`)
  - Verification steps and pasted terminal output
  - Mandatory Pre-Submission Governance checklist. Select each box after you complete its check.

### 6. Open PR as DRAFT First
- Open all pull requests in Draft mode (`gh pr create --draft` or choose "Create draft pull request" in GitHub).
- Draft PRs allow CI workflows to run in isolation without triggering premature reviewer notifications or consuming unnecessary review capacity.
- Wait for all CI checks to pass on the draft. Make sure the change works locally.

### 7. Mark Ready for Review
- Only after all local and draft CI checks have succeeded, convert the pull request to "Ready for Review".
- The project can return a PR to draft or close it. This can occur if checks fail or the PR has missing template fields or verification.

### 8. Automated Quality Gates and Merge Criteria
A pull request must pass all automated checks before merge.
- CodeRabbit AI Review. Address all review comments and suggestions.
- GitHub Copilot Code Review: Must pass with no blocking feedback.
- Codecov Coverage Reports: Must pass with zero errors, zero warnings, and no coverage regressions below the repository target.
- Branch Ruleset Checks: All required status checks defined in the default branch ruleset must pass.

---

## Local Development and Verification

### Prerequisites and Setup

- Python 3.11 or later
- Dependencies installed through `uv sync` or `pip install -e ".[test,dev]"`
- Pre-commit (`pre-commit install`)

### Validation Commands

```bash
# Run test suite with pytest
pytest -v

# Run tests with code coverage
pytest --cov=src --cov-report=term-missing

# Lint and check formatting with ruff
ruff check .
ruff format --check .

# Static type checking with mypy (library and the script/ tooling)
mypy src script

# Run pre-commit checks
pre-commit run --all-files
```

---

## Upstream Watch

The `Upstream watch` workflow (`.github/workflows/upstream-watch.yml`) monitors
[unraid/api](https://github.com/unraid/api) for changes.
It runs at 02:00 Australia/Brisbane on the first and fifteenth day of each month.
To start it manually, use the Actions tab (`workflow_dispatch`).
You can specify the `since` and `until` release tags.

The scan reads only public data. The report job creates issues only on `main` in this repository.
It uses `redirect.github.com` for upstream PR links. This prevents GitHub from adding "mentioned this" entries upstream.

- **Scan job** (read-only): `script/upstream_watch.py scan` diffs `api/generated-schema.graphql`
  between each pair of consecutive new release tags. It also compares the latest release with `main`.
  The job uses `graphql.validate` to validate each library operation against each new schema.
  It lists the library methods and `file:line` locations that select changed fields.
  It flags release notes and linked PRs about introspection, request limits,
  authentication, rate limiting, or error formats. It writes one JSON report.
- **Report job** (`issues: write` only). The job opens one issue for each group of findings.
  It writes a summary of all releases and changes it checked, including changes that need no action.

**Labels.** The report job opens an issue with `bug` and `upstream` for a behavior change
or one of these breaking changes.

- An operation fails schema validation.
- The schema removes a selected field or root, or changes it to nullable.
- An input type or enum in the library's variables loses a field or value.
- An input field changes type, or an input type adds a required field.
- A non-null input field loses its default.

The job uses `enhancement` and `upstream` for new types, fields, root fields, and deprecations.
It creates each missing label before use. It sets the labels when it creates the issue.
Issues that use `GITHUB_TOKEN` do not start the issue labeler.

**Markers and state.** Each issue body starts with hidden markers: `<!-- upstream-group: ... -->`,
`<!-- upstream-release: vX.Y.Z -->` (or `<!-- upstream-main: <sha> -->`) and one
`<!-- upstream-change: <id> -->` per change. The job uses markers only from
`github-actions[bot]` issues.

The job checks open and closed issues. It does not reopen issues you close. It does not report a change from `main` again when a release includes it.

The closed `Upstream watch state` issue (label `upstream`) records the last release and
`main` commit that the job processed. The scanner reads its cursor only from this issue. The report job updates the issue last.
If a run fails before this update, the next run repeats the scan. Leave it closed and do not edit its markers. A group whose markers
would not fit in one issue body is split into numbered parts.

Run the scan locally. It writes only the report file.

```bash
GITHUB_TOKEN=$(gh auth token) uv run --all-extras python script/upstream_watch.py scan \
  --since v4.37.6 --until v4.37.9 --output report.json
```

Validate the library against a schema without a server (Unraid API 4.37.8+ refuses introspection):

```bash
uv run --all-extras python scripts/validate-schema.py --schema-file generated-schema.graphql --schema-only
uv run --all-extras python scripts/validate-schema.py --api-version 4.37.9 --schema-only
```

Without these options, `validate-schema.py` gets the upstream SDL for the server's API version.
Use `--introspect` to read the schema directly from the server.

---

## Commit Message Guidelines

We follow Conventional Commits:

- `feat(<scope>): <description>` — New feature
- `fix(<scope>): <description>` — Bug fix
- `docs(<scope>): <description>` — Documentation changes
- `test(<scope>): <description>` — Adding or updating tests
- `refactor(<scope>): <description>` — Code restructuring without functional change
- `chore(<scope>): <description>` — Tooling, dependencies, or repository maintenance

---

## Pull Request Governance Summary

- No spam or back-to-back PRs: Batch related changes into a single PR.
- AI-assisted PRs require human verification and local testing before submission.
- Complete all required template checks.
- PRs must remain in Draft until verified.

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
