# Changelog

Notable changes to proofline. The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow the schema evolution rules in `spec/run-bundle-v0.1.md`.

## Unreleased

### Changed

- Canonical JSON is strict: `NaN` and `Infinity` are rejected anywhere in a bundle, keeping digests portable across languages (spec updated accordingly).
- Redaction pointer resolution follows RFC 6901: array indices with leading zeros no longer resolve.

### Added

- `proofline --version`.
- `RunRecorder.step` fails fast with a clear `TypeError` when the step input is not JSON-serializable, instead of crashing while the step is being recorded, and snapshots the input at entry so mutating the passed object during the step cannot alter the recorded evidence.
- `proofline.testing.assert_matches_baseline`: snapshot-style baseline assertion for test suites, with `PROOFLINE_UPDATE_BASELINES=1` to re-record.
- Release workflow publishing to PyPI via trusted publishing on version tags.
- `proofline run` records the child process stdout/stderr: a SHA-256 digest of the exact bytes plus a capped UTF-8 text preview, echoed byte-exact after completion.
- `wrap()` in the OpenAI and Anthropic integrations detects `AsyncOpenAI` / `AsyncAnthropic` clients and records async calls, including async streaming with the same exactly-once and truncation semantics as the sync path.
- CI regression gate guide (`docs/ci-regression.md`) and a README FAQ on positioning and guarantees.
- Contributor guide, security policy with explicit redaction boundaries, and issue/PR templates.

## 0.1.1

First public release.

### Fixed

- Failed streamed requests were recorded as `ok` steps; streamed steps now record exactly once with a `truncated` flag via a shared lifecycle.
- `verify` resolves every redaction JSON Pointer per spec and no longer carries a dead `bundle_digest` leak filter.
- `actor.version` records the package version instead of the schema version.

### Added

- Anthropic integration (`proofline.anthropic.wrap`) behind an optional extra.
- JSON Schema conformance tests pinning `schemas/run.schema.json` to the implementation constants.
- Redaction coverage for plural key forms and AWS, JWT, GitHub PAT, Slack, and PEM value patterns.
- MIT license file, project URLs, CI packaging checks, and negative-path tests for verify, CLI, policy, and redaction.

### Removed

- Unenforced policy surface (`allow_shell`, `allow_network`, `check_command`, `check_network`); `Policy` keeps the enforced write-root check.

## 0.1.0

Initial version: run bundle recorder, stable digest over canonical JSON, secret redaction with JSON Pointer tracking, verification, semantic diff, `proofline run/verify/diff` CLI, and the OpenAI chat completions wrapper.
