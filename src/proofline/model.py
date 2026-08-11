from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "0.1"
VOLATILE_TOP_LEVEL = {"run_id", "created_at", "bundle_digest"}
VOLATILE_STEP_FIELDS = {"started_at", "ended_at"}


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
