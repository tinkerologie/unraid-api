# Contributing to Unraid API Python Library

Thank you for your interest in contributing to Unraid API Python Library. This project welcomes contributions from human developers and autonomous AI coding agents alike.

Python client library and CLI for interacting with the Unraid Management Agent REST/WebSocket API.

To maintain code quality, protect maintainer capacity, and prevent maintainer burnout, all contributors must follow the standardized development and governance workflow outlined below.

---

## Code of Conduct and Standards

- Be respectful, constructive, and collaborative.
- Zero secrets policy: Never commit passwords, tokens, API keys, private certificates, or personal data.
- Anti-burnout principle: Perform full due diligence locally before opening pull requests or requesting review.

---

## Development Workflow

All contributions—whether submitted by humans or AI agents—must adhere to this step-by-step workflow:

### 1. Open a GitHub Issue First
- Every bug fix, feature, or enhancement must start with an issue.
- Use the appropriate GitHub Issue Form:
  - Bug Report (`01-bug-report.yml`)
  - Enhancement Request (`02-enhancement-request.yml`)
- Blank or unstructured issues are disabled. Pull requests without a corresponding issue will be closed.

### 2. CodeRabbit AI Plan Generation
- Once the issue is created, CodeRabbit AI is triggered to generate an implementation plan (either automatically via the `bug` or `enhancement` label, or by commenting `@coderabbitai plan` on the issue).
- CodeRabbit analyzes the codebase and posts a comprehensive Coding Plan containing:
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
- Never commit directly to the default branch (`main`).

### 4. Implementation and Local Validation
- Implement changes following project conventions and the approved plan.
- Update `CHANGELOG.md` under `## [Unreleased]` describing what changed and why.
- Run all required local validation checks (tests with coverage, linters, type checkers, and formatters). Ensure all checks pass with zero errors and zero warnings.

### 5. Follow the Pull Request Template
- Open a Pull Request using `.github/PULL_REQUEST_TEMPLATE.md`.
- Complete all sections in the template:
  - Summary of changes
  - Linked issue keywords (`Fixes #<issue>`, `Closes #<issue>`, `Addresses #<issue>`)
  - Verification steps and pasted terminal output
  - Mandatory Pre-Submission Governance checklist (every box must be checked)

### 6. Open PR as DRAFT First
- Pull requests MUST be opened in Draft mode (`gh pr create --draft` or choose "Create draft pull request" in GitHub).
- Draft PRs allow CI workflows to run in isolation without triggering premature reviewer notifications or consuming unnecessary review capacity.
- Verify that all CI checks pass in draft mode and confirm that everything is working as expected from your end.

### 7. Mark Ready for Review
- Only after all local and draft CI checks have succeeded, convert the pull request to "Ready for Review".
- Pull requests marked ready for review with failing checks, incomplete templates, or unverified changes will be converted back to draft or closed.

### 8. Automated Quality Gates and Merge Criteria
Before a pull request can be merged, it must satisfy all automated quality gates:
- CodeRabbit AI Review: All review comments and suggestions must be resolved or addressed.
- GitHub Copilot Code Review: Must pass with no blocking feedback.
- Codecov Coverage Reports: Must pass with zero errors, zero warnings, and no coverage regressions below the repository target.
- Branch Ruleset Checks: All required status checks defined in the default branch ruleset must pass.

---

## Local Development and Verification

### Prerequisites and Setup

- Python 3.11 or later
- Dependencies installed via `uv sync` or `pip install -e ".[test,dev]"`
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

The `Upstream watch` workflow (`.github/workflows/upstream-watch.yml`) tracks
[unraid/api](https://github.com/unraid/api) so upstream changes reach this library early. It runs
at 02:00 Australia/Brisbane on the 1st and 15th of each month, and on demand from the Actions tab
(`workflow_dispatch`, with optional `since`/`until` release tags).

- **Scan job** (read-only): `script/upstream_watch.py scan` diffs `api/generated-schema.graphql`
  between consecutive new release tags and from the latest release to `main`, validates every
  library operation against each new schema with `graphql.validate`, maps changed fields to the
  library methods and `file:line` that select them, and flags release notes and linked PRs that
  change request handling (introspection, request limits, auth, rate limiting, error shapes). It
  writes one JSON report.
- **Report job** (`issues: write` only): opens one issue per finding group and writes the report to
  the job summary, which lists every release and change checked, including those that need no
  action.

**Labels.** Breaking changes (an operation no longer validates; a field or root the library
selects was removed or became nullable; or an input type or enum the library sends in variables
lost a field or value, changed a field's type, or gained a required field) and behaviour changes
open a `bug` + `upstream` issue. New
types, fields and root fields, and new deprecations, open an `enhancement` + `upstream` issue. The
job creates a missing label before use, and sets labels in the create call, because issues opened
with `GITHUB_TOKEN` do not trigger the issue labeler.

**Markers and state.** Each issue body starts with hidden markers: `<!-- upstream-group: ... -->`,
`<!-- upstream-release: vX.Y.Z -->` (or `<!-- upstream-main: <sha> -->`) and one
`<!-- upstream-change: <id> -->` per change. Only markers in issues authored by
`github-actions[bot]` count, open or closed, so closing an issue does not reopen it, and a change
first reported from `main` is not reported again when it ships in a release. The closed
`Upstream watch state` issue (label `upstream`) records the last processed release and `main`
commit, and is the only source of the scan cursor; the report job updates it last, so a run that
fails midway is retried in full. Leave it closed and do not edit its markers. A group whose markers
would not fit in one issue body is split into numbered parts.

Run the scan locally (read-only; writes only the report file):

```bash
GITHUB_TOKEN=$(gh auth token) uv run --all-extras python script/upstream_watch.py scan \
  --since v4.37.6 --until v4.37.9 --output report.json
```

Validate the library against a schema without a server (Unraid API 4.37.8+ refuses introspection):

```bash
uv run --all-extras python scripts/validate-schema.py --schema-file generated-schema.graphql --schema-only
uv run --all-extras python scripts/validate-schema.py --api-version 4.37.9 --schema-only
```

Without these options, `validate-schema.py` fetches the upstream SDL for the server's API version;
`--introspect` keeps the old live-introspection path.

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
- All template checkboxes must be confirmed.
- PRs must remain in Draft until verified.

## Issue and Pull Request Governance

These rules apply to every contributor, including AI coding agents. The full org-wide rules are in
[GOVERNANCE.md](https://github.com/tinkerologie/.github/blob/main/GOVERNANCE.md).

1. **Issue first.** Open an issue with the bug or enhancement template before opening a pull
   request. Keep the title prefix `[Bug]:` or `[Enhancement]:`, followed by a space and the title.
   Automation applies the `bug` or `enhancement` label when it can tell the type, and CodeRabbit
   then posts a Coding Plan on the issue. Implement from that plan. The labeler skips issues labeled
   `question`, `duplicate`, `invalid`, `wontfix`, or `no-type`, and never re-adds a type label that
   a maintainer removed.
2. **Link the issue.** In the PR's **Related Issues** section, write `Closes #<number>` (or `Fixes`
   or `Resolves`) when the PR completely resolves the issue; these keywords close it on merge. Use
   `Part of #<number>` or `Related to #<number>` for partial work. The linked issue must exist; an
   issue in another public repository (`owner/repo#123`) is fine. Only authors with write access or
   higher (maintainers) may write `None`, for housekeeping such as CI,
   documentation, or dependency updates; PR governance rejects `None` from everyone else.
3. **One change at a time.** Contributors without write access can have at most 2 open, non-draft
   pull requests here. GitHub enforces this limit, and draft pull requests do not count toward it.
   Do not open PRs that edit the same files as another open PR, such as `CHANGELOG.md`,
   translations, `README.md`, or generated bundles. Wait for the first to merge, rebase, then
   continue.
4. **Act on the Tinkerologie-Bot report.** When PR governance fails, Tinkerologie-Bot posts one comment
   listing every problem as a numbered item. Fix each item by editing the PR description or pushing
   the missing change; the check re-runs and the comment updates to passed.
5. **Rebase before review.** Rebase on `main` before marking a PR ready for review.
6. **Resolve conflicts first.** When a PR gets the `conflicts` label, rebase on `main`,
   resolve the conflicts (keep every `CHANGELOG.md` entry under `[Unreleased]`), re-run the tests,
   and force-push before doing any other work.
7. **Coverage.** `codecov/patch` must pass: at least 95% of added or changed lines must be
   covered by tests. The gate is the percentage; still, add tests for the uncovered lines the
   Codecov PR comment lists, and explain in the PR description any line you leave uncovered. Do
   not lower coverage targets or add coverage ignore rules to make it pass.
8. **Stale items.** Issues and PRs with no activity for 14 days are labeled `stale` and closed 30
   days later unless there is new activity. These labels are exempt:
   - Issues: `pinned`, `security`, `confirmed`, `work-in-progress`, `priority: critical`, `priority: high`.
   - Pull requests: `pinned`, `security`, `work-in-progress`.
