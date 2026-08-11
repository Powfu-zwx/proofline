"""Baseline assertions for using run bundles in test suites.

Works with any test runner. Record a blessed baseline once, then fail the
test whenever a new run semantically diverges from it; see
``docs/ci-regression.md`` for the full workflow.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .diff import diff_bundles
from .storage import read_bundle, write_bundle
from .verify import assert_valid

UPDATE_ENV = "PROOFLINE_UPDATE_BASELINES"


def _without_update_env(bundle: dict[str, Any]) -> dict[str, Any]:
    """Drop the helper's own switch from env_keys so recording never poisons a baseline."""
    invocation = bundle.get("invocation")
    if not isinstance(invocation, dict) or not isinstance(invocation.get("env_keys"), list):
        return bundle
    filtered = dict(bundle)
    filtered["invocation"] = {
        **invocation,
        "env_keys": [key for key in invocation["env_keys"] if key != UPDATE_ENV],
    }
    return filtered


def assert_matches_baseline(
    bundle_or_path: str | Path | dict[str, Any], baseline_path: str | Path
) -> None:
    """Assert that a bundle semantically matches the stored baseline.

    The bundle is verified first, so a tampered or malformed candidate fails
    before any comparison. Set ``PROOFLINE_UPDATE_BASELINES=1`` to (re)write
    the baseline instead of asserting, then commit the updated file; the
    variable itself is excluded from the comparison.
    """
    if isinstance(bundle_or_path, (str, Path)):
        bundle = read_bundle(bundle_or_path)
    else:
        bundle = bundle_or_path
    assert_valid(bundle)

    path = Path(baseline_path)
    if os.environ.get(UPDATE_ENV):
        write_bundle(path, bundle)
        return
    if not path.exists():
        raise AssertionError(
            f"baseline does not exist: {path}; run once with {UPDATE_ENV}=1 to record it"
        )
    differences = diff_bundles(
        _without_update_env(read_bundle(path)), _without_update_env(bundle)
    )
    if differences:
        listing = "\n".join(differences)
        raise AssertionError(f"run diverged from baseline {path}:\n{listing}")
