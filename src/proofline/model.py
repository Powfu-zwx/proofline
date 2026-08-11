from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "0.1"
PACKAGE_VERSION = "0.1.0"

VOLATILE_TOP_LEVEL = {"run_id", "created_at", "bundle_digest"}
VOLATILE_STEP_FIELDS = {"started_at", "ended_at"}

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


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in bundle.items() if key not in VOLATILE_TOP_LEVEL}
    normalized["steps"] = [
        {key: value for key, value in step.items() if key not in VOLATILE_STEP_FIELDS}
        for step in bundle.get("steps", [])
    ]
    return normalized


def stable_digest(bundle: dict[str, Any]) -> str:
    return sha256_json(stable_bundle(bundle))
