# Contributing

Thanks for your interest in proofline. This is a small, spec-first project; contributions that keep it small and verifiable are the most welcome.

## Development setup

```bash
git clone https://github.com/Powfu-zwx/proofline.git
cd proofline
python -m pip install -e ".[dev]"
```

Run the checks that CI runs:

```bash
ruff check src tests examples
pytest -q
```

Python 3.11+ is required. The core package has zero runtime dependencies; provider integrations live behind optional extras (`[openai]`, `[anthropic]`) and are tested with fakes, so you do not need API keys to run the test suite.

## Before you open a PR

- For bug fixes: include a test that fails without the fix.
- For behavior or schema changes: open an issue first. The run-bundle format is a versioned contract (`spec/run-bundle-v0.1.md` + `schemas/run.schema.json`); in `0.1.x` only additive optional fields are allowed, and `tests/test_schema.py` pins the schema to the constants in `src/proofline/model.py`.
- Keep the dependency policy: no new runtime dependencies in the core package; integrations go behind extras and must degrade to duck-typed fakes in tests.
- Match the existing style: `ruff` clean, no narrating comments, one source of truth per rule.

## Project layout

| Path | Purpose |
|---|---|
| `src/proofline/model.py` | Schema constants, canonical JSON, stable digest (single source of truth) |
| `src/proofline/recorder.py` | `RunRecorder` and step lifecycle |
| `src/proofline/redact.py` | Secret redaction and leak scanning |
| `src/proofline/verify.py` | Bundle verification |
| `src/proofline/diff.py` | Semantic diff |
| `src/proofline/_stream.py` | Shared streamed-call step lifecycle |
| `spec/` | Human-readable protocol spec |
| `schemas/` | JSON Schema for the bundle format |

## Releases

Maintainer checklist: tests green, bump `PACKAGE_VERSION` in `src/proofline/model.py`, build + `twine check`, tag `vX.Y.Z`, push, upload to PyPI, publish the GitHub Release, smoke-test `pip install proofline` in a clean environment.
