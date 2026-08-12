# Security Policy

## What redaction does and does not guarantee

Proofline redacts secrets before a bundle is written, using two pattern families:

- key patterns (`api_key`, `token`, `secret`, `password`, `credentials`, ...)
- value patterns (`sk-...`, `AKIA...`, `ghp_...`, `github_pat_...`, `xox...`, JWTs, `Bearer ...`, PEM private keys)

This is best-effort, pattern-based protection. It will not catch secrets with unusual names or formats, secrets embedded in encoded blobs, or domain-specific sensitive data. `proofline verify` re-scans bundles for the same patterns as a second line of defense, but a passing verification is not a guarantee that a bundle contains no sensitive data.

Treat run bundles as potentially sensitive artifacts: review them before sharing, and prefer digest-plus-reference storage for values you would not commit to a repository.

## What the digest does and does not guarantee

The stable digest detects corruption and careless edits; it does not stop a forger who recomputes it after editing. For tamper evidence, sign bundles (`proofline sign`, see `docs/signing.md`): the signature covers the full document, so re-sealing breaks it. Private key custody is then your responsibility — treat signing keys like deploy keys.

## Supported versions

Only the latest released minor version receives fixes.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting (Security tab → Report a vulnerability) on this repository. Do not open public issues for suspected leaks or bypasses of the redaction patterns. You can expect a first response within a few days; this is a single-maintainer project.
