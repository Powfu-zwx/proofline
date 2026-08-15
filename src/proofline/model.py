from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "0.1"
PACKAGE_VERSION = "0.4.0"

# Signatures attest to a bundle; they are not recorded evidence, so they are
# excluded from the stable digest and from semantic diffs.
VOLATILE_TOP_LEVEL = {"run_id", "created_at", "bundle_digest", "signatures"}
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
    """Strict canonical JSON; NaN and Infinity are rejected to keep bundles portable."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in bundle.items() if key not in VOLATILE_TOP_LEVEL}
    normalized["steps"] = [
        {key: value for key, value in step.items() if key not in VOLATILE_STEP_FIELDS}
        for step in bundle.get("steps", [])
    ]
    return normalized


def stable_step(step: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in step.items() if key not in VOLATILE_STEP_FIELDS}


def stable_digest(bundle: dict[str, Any]) -> str:
    return sha256_json(stable_bundle(bundle))


class StableDigestBuilder:
    """SHA-256 over a bundle's stable form, streaming steps one at a time.

    Produces exactly ``stable_digest(bundle)`` without materializing the
    canonical JSON of the whole document: the header (every non-volatile
    field except ``steps``, with ``redactions`` final) is hashed once, then
    each step as it is added, so peak memory is bounded by the largest step
    rather than the bundle. Steps must be added in recorded order.
    """

    def __init__(self, header: dict[str, Any]) -> None:
        core = canonical_json(header)[:-1]  # drop the closing brace
        prefix = f'{core},"steps":[' if core != "{" else '{"steps":['
        self._hash = hashlib.sha256(prefix.encode("utf-8"))
        self._count = 0
        self._sealed = False

    def add_step(self, step: dict[str, Any]) -> None:
        if self._sealed:
            raise RuntimeError("steps cannot be added after hexdigest()")
        if self._count:
            self._hash.update(b",")
        self._hash.update(canonical_json(stable_step(step)).encode("utf-8"))
        self._count += 1

    def hexdigest(self) -> str:
        digest = self._hash.copy()
        digest.update(b"]}")
        self._sealed = True
        return digest.hexdigest()
