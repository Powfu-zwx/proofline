from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import SCHEMA_VERSION, sha256_json, stable_digest
from .redact import contains_unredacted_secret
from .storage import read_bundle

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "run_id",
    "created_at",
    "actor",
    "project",
    "invocation",
    "steps",
    "redactions",
    "bundle_digest",
}
REQUIRED_STEP = {"step_id", "kind", "name", "status", "started_at", "ended_at"}
STEP_KINDS = {"model", "tool", "file", "network", "process", "custom"}
STEP_STATUSES = {"ok", "error", "skipped"}


class VerificationError(ValueError):
    pass


def verify_bundle(bundle_or_path: str | Path | dict[str, Any]) -> list[str]:
    if isinstance(bundle_or_path, (str, Path)):
        bundle = read_bundle(bundle_or_path)
    else:
        bundle = bundle_or_path
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["bundle must be a JSON object"]

    missing = sorted(REQUIRED_TOP_LEVEL - set(bundle))
    if missing:
        errors.append(f"missing top-level fields: {', '.join(missing)}")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {bundle.get('schema_version')!r}")

    steps = bundle.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be an array")
        steps = []

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"steps[{index}] must be an object")
            continue
        step_missing = sorted(REQUIRED_STEP - set(step))
        if step_missing:
            errors.append(f"steps[{index}] missing fields: {', '.join(step_missing)}")
        if step.get("kind") not in STEP_KINDS:
            errors.append(f"steps[{index}].kind is invalid: {step.get('kind')!r}")
        if step.get("status") not in STEP_STATUSES:
            errors.append(f"steps[{index}].status is invalid: {step.get('status')!r}")
        if step.get("input") is not None and step.get("input_digest") != sha256_json(
            step.get("input")
        ):
            errors.append(f"steps[{index}].input_digest mismatch")
        if step.get("output") is not None and step.get("output_digest") != sha256_json(
            step.get("output")
        ):
            errors.append(f"steps[{index}].output_digest mismatch")

    digest = bundle.get("bundle_digest")
    if "bundle_digest" in bundle and (
        not isinstance(digest, str) or digest != stable_digest(bundle)
    ):
        errors.append("bundle_digest mismatch")

    leaks = [
        path
        for path in contains_unredacted_secret(bundle)
        if not path.endswith("/bundle_digest")
    ]
    if leaks:
        errors.append(f"possible unredacted secrets at: {', '.join(leaks)}")

    redactions = bundle.get("redactions")
    if not isinstance(redactions, list) or any(not isinstance(path, str) for path in redactions):
        errors.append("redactions must be an array of JSON Pointer strings")

    return errors


def assert_valid(bundle_or_path: str | Path | dict[str, Any]) -> None:
    errors = verify_bundle(bundle_or_path)
    if errors:
        raise VerificationError("\n".join(errors))
