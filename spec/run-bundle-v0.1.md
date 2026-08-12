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

## Signatures

The stable digest detects accidental corruption, but anyone who edits a bundle can recompute it. The optional top-level `signatures` array carries detached signatures that make tampering evident under a key.

- Each entry has `algorithm` (`ed25519`), `public_key` (base64 raw key), `signature` (base64), and may carry `key_id` and `signed_at`.
- The signed payload is the canonical JSON of the bundle with the `signatures` field removed. It therefore covers every other field, including volatile ones and `bundle_digest`, so re-sealing a tampered bundle invalidates the signature.
- `signatures` is excluded from the stable digest and from semantic diffs: signing does not change what the bundle proves, only who vouches for it.
- Verifiers must reject entries with unknown algorithms or invalid signatures. An embedded public key proves integrity under that key; proving identity additionally requires pinning the expected key out of band.

## Verification

Verification must check:

1. Required top-level fields and step fields exist.
2. `schema_version` is supported.
3. Every stored step digest matches the canonical JSON of its recorded content.
4. Every redaction path is a JSON Pointer that resolves inside the bundle.
5. No value in the bundle matches an obvious secret pattern.
6. The stable digest matches the normalized bundle.
7. When `signatures` is present, every entry verifies against the signed payload.

## Evolution

Additive optional fields may be introduced in `0.1.x`. Required-field changes, semantic changes to existing fields, or digest changes require a new schema version.
