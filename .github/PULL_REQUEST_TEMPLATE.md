# Pull Request

## Description

<!-- Describe the change. -->

## Type of Change

<!-- Check all that apply -->

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature or endpoint support
- [ ] Breaking change (change that modifies public API signatures or behavior)
- [ ] Documentation update
- [ ] Code refactoring (no functional changes)
- [ ] Test additions or improvements
- [ ] Dependency update

## Pre-Submission Governance

<!--
  All contributors, AI agents, and automation must complete this checklist.
  The PR Governance check fails if a box is empty.
  The PR must pass this check before review or merge.
  Put related changes in one PR to limit the number of CI runs.
-->

- [ ] I built and tested the package locally and verified this change actually works
- [ ] I ran pytest locally and all tests pass
- [ ] I ran linter / type checks locally and they pass
- [ ] I pasted real local verification output under **Testing Performed** below (no placeholder text)
- [ ] This PR is self-contained and is not a duplicate; I have not opened other overlapping or back-to-back PRs for the same change
- [ ] If an AI agent created or assisted with this PR, a human reviewed and verified the changes before submission

## Related Issues

<!-- Link the issue this PR resolves (Closes #123) or contributes to (Part of #123). "None" is only for maintainers with write access, for housekeeping. -->
<!-- Examples: Fixes #123, Closes https://github.com/..., Related to #456, Part of #789, or None (maintainers only) -->

Fixes #

## Changes Made

<!-- List the main changes. -->

-
-
-

## Python Package & API Architecture Standards

<!-- Check all that apply to confirm compliance with Python library quality standards -->

- [ ] Type annotations present and compliant with PEP 561 (`py.typed`)
- [ ] Async/await patterns followed where applicable (aiohttp/httpx)
- [ ] Custom library exceptions raised (no raw swallowed errors or bare excepts)
- [ ] No raw `print()` statements in package source code (uses standard logging)
- [ ] Sensitive credentials (tokens, passwords, API keys) redacted from logs and `__repr__`
- [ ] Not applicable (documentation-only or metadata change)

## Testing Performed

<!-- Select each check you ran. Describe what you tested. -->

- [ ] Ran unit tests (`pytest`)
- [ ] Ran linter (`ruff` or `flake8`)
- [ ] Ran type checking (`mypy`)
- [ ] Tested against live device or recorded fixtures
- [ ] Not applicable (documentation-only or metadata-only change)

### Test Results

```text
[Paste relevant local command output and verification notes]
```

## Documentation

<!-- Check all that apply -->

- [ ] Docstrings added/updated where needed
- [ ] README.md updated (if needed)
- [ ] CHANGELOG.md updated under [Unreleased]
- [ ] AGENTS.md / developer documentation updated (if architecture or process changed)
- [ ] No documentation needed

## Breaking Changes

<!-- Describe each breaking change. Give the migration steps. -->

## Checklist

<!-- Complete each required item before you submit the PR. -->

- [ ] I have updated CHANGELOG.md under [Unreleased] with details of this change
- [ ] I linked the related issue in **Related Issues** (only maintainers may note "None", for housekeeping)
- [ ] I completed all required sections in this template and removed placeholder-only content
- [ ] My code follows the project's coding standards and Python best practices
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas (if applicable)
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works (if applicable)
- [ ] New and existing tests pass locally with my changes
- [ ] No sensitive information (tokens, passwords, personal data) is included
