# Changelog

Notable changes to proofline. The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow the schema evolution rules in `spec/run-bundle-v0.1.md`.

## 0.4.0

### Added

- Crash-safe journaling (`proofline.journal`, `RunRecorder(..., journal=True)`): every completed step is appended and fsynced to a JSONL journal the moment it finishes, so a process that dies mid-run loses at most the step it was executing. `proofline recover` rebuilds and verifies the bundle from the journal; a torn final line is detected and dropped, a corrupt interior line is a hard error, and the journal is only removed after the bundle write succeeded. `proofline run --journal` records subprocess runs the same way. See `docs/journal.md`.
- Journal mode streams step payloads to disk instead of accumulating them in memory, so recording a long run costs the memory of the largest step, not of the whole run.
- `StableDigestBuilder`: the stable digest computed incrementally, one step at a time, without materializing the canonical JSON of the whole document. Bit-identical to `stable_digest` by construction and property test; the digest rules and the TypeScript port's byte-level parity are unchanged.
- `proofline diff` aligns step sequences before comparing: an inserted or removed step reports once (`added step` / `removed step`) instead of shifting every following step out of alignment, and a changed step pairs with its counterpart by `(kind, name)` to report field-level differences. Positional `step_id`s are treated as derived and excluded, since the alignment lines already describe any shift. Non-step lists keep their element-wise comparison.
- `examples/semantic_diff_demo.py`: a deterministic, offline guided tour with the naive JSON diff as the control group — identical reruns (20 noise lines vs "no semantic differences"), a one-line prompt change (hash churn vs the exact field), an inserted tool step (one line, not four misaligned steps), and a tamper scene where an edited answer is caught, survives a digest re-seal, and falls to the signature.

### Changed

- Journal mode records `created_at` at recorder construction, so a recovered bundle reports when the run began rather than when it was recovered; memory mode still seals at `finalize()` as before.
- In journal mode, a step output that is not strict-JSON-serializable fails at the end of that step instead of at `finalize()`, and `Policy.check_write_path` is enforced on the journal path at construction.

## 0.3.0

### Added

- Detached Ed25519 signatures (`proofline.sign`, optional `[sign]` extra): the signed payload covers the whole document including volatile fields and `bundle_digest`, so editing anything and re-sealing the digest invalidates the signature. New CLI commands `proofline keygen` and `proofline sign`, plus `proofline verify --signed-by` for key pinning. `verify` validates any signatures a bundle carries.
- Optional top-level `signatures` field in the schema and spec, excluded from the stable digest and from semantic diffs.
- Signing guide (`docs/signing.md`) including keyless CI signing and transparency logging via Sigstore.

## 0.2.0

### Added

- Replay (`proofline.replay`): recorded model responses are served back through the wrappers, so a bundle doubles as a deterministic, offline test fixture. `strict` matching by redacted-input digest for fixture tests, `ordered` matching for attribution diffs, `PROOFLINE_REPLAY` for zero-code activation in CI, and chunk-by-chunk streaming replay. See `docs/replay.md`.
- Streamed steps record the individual text chunks (`output.chunks`) alongside the accumulated content.
- `proofline --version`.
- `RunRecorder.step` fails fast with a clear `TypeError` when the step input is not JSON-serializable, instead of crashing while the step is being recorded, and snapshots the input at entry so mutating the passed object during the step cannot alter the recorded evidence.
- `proofline.testing.assert_matches_baseline`: snapshot-style baseline assertion for test suites, with `PROOFLINE_UPDATE_BASELINES=1` to re-record.
- Release workflow publishing to PyPI via trusted publishing on version tags.
- `proofline run` records the child process stdout/stderr: a SHA-256 digest of the exact bytes plus a capped UTF-8 text preview, echoed byte-exact after completion.
- `wrap()` in the OpenAI and Anthropic integrations detects `AsyncOpenAI` / `AsyncAnthropic` clients and records async calls, including async streaming with the same exactly-once and truncation semantics as the sync path.
- CI regression gate guide (`docs/ci-regression.md`) and a README FAQ on positioning and guarantees.
- Contributor guide, security policy with explicit redaction boundaries, and issue/PR templates.

### Changed

- Canonical JSON is strict: `NaN` and `Infinity` are rejected anywhere in a bundle, keeping digests portable across languages (spec updated accordingly).
- Redaction pointer resolution follows RFC 6901: array indices with leading zeros no longer resolve.

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
