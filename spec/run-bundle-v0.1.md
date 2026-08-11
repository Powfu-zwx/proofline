# Proofline Run Bundle v0.1

A run bundle is a JSON document describing one bounded AI execution. It is designed for replay, review, audit, and regression testing across model providers and agent frameworks.

## Requirements

- `schema_version` must be `0.1`.
- `run_id` identifies a physical emission of a bundle. It is volatile and excluded from the stable digest.
- `created_at`, step `started_at`, and step `ended_at` are volatile and excluded from the stable digest.
- `project.revision` should be a commit hash when the run happens inside a VCS repository.
- Secret material must be redacted before a bundle is written. Redactions are recorded as JSON Pointer paths.
- Step inputs and outputs may be stored inline for small values. Large or sensitive values should be replaced by content digests plus external storage references.

## Stable digest

`bundle_digest` is SHA-256 over canonical JSON of the bundle after removing `run_id`, `created_at`, `bundle_digest`, and every step `started_at` / `ended_at`. Canonical JSON uses sorted keys, UTF-8, no insignificant whitespace, and `ensure_ascii=false`. Canonical JSON must be strict JSON: `NaN` and `Infinity` are invalid anywhere in a bundle.

## Verification

Verification must check:

1. Required top-level fields and step fields exist.
2. `schema_version` is supported.
3. Every stored step digest matches the canonical JSON of its recorded content.
4. Every redaction path is a JSON Pointer that resolves inside the bundle.
5. No value in the bundle matches an obvious secret pattern.
6. The stable digest matches the normalized bundle.

## Evolution

Additive optional fields may be introduced in `0.1.x`. Required-field changes, semantic changes to existing fields, or digest changes require a new schema version.
