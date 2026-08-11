## What this changes

## Why

Link the issue if one exists. For behavior or schema changes without a prior issue, expect discussion before merge.

## Checklist

- [ ] `ruff check src tests examples` passes
- [ ] `pytest -q` passes, new behavior has tests
- [ ] No new runtime dependencies in the core package
- [ ] Schema/spec untouched, or updated together with `tests/test_schema.py`
