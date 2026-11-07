# Architecture decisions

These records describe existing architecture, checked against `a72d632` on
2026-11-07. They record observable contracts and documented trade-offs
retrospectively; the recording date is not an asserted original decision date.
Proposed changes belong in GitHub Issues until a decision is accepted.

Read the [domain glossary](../../GLOSSARY.md) for terminology.

| ADR | Decision |
| --- | --- |
| 0001 | [Keep transport lifecycle in the asynchronous client](0001-client-owns-transport-lifecycle.md) |
| 0002 | [Adapt operations to server capabilities](0002-capability-driven-compatibility.md) |
| 0003 | [Normalize server data while preserving meaningful query failures](0003-typed-models-and-partial-results.md) |
| 0004 | [Expose explicit read variants for standby-sensitive polling](0004-standby-aware-reads.md) |
| 0005 | [Require verified HTTPS for array decryption credentials](0005-encrypted-array-start-transport.md) |
