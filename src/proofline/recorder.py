from __future__ import annotations

import getpass
import json
import os
import platform
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .model import (
    PACKAGE_VERSION,
    SCHEMA_VERSION,
    STEP_KINDS,
    canonical_json,
    sha256_json,
    stable_digest,
    utc_now,
)
from .policy import Policy
from .redact import redact
from .storage import write_bundle


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _qualify_redactions(paths: list[str], prefix: str) -> list[str]:
    return [prefix if path == "/" else f"{prefix}{path}" for path in paths]


class RunRecorder:
    """Record one bounded execution as a verifiable run bundle.

    Steps are recorded with :meth:`step`; :meth:`finalize` seals the bundle
    with its stable digest and optionally writes it. Instances are not
    thread-safe: use one recorder per thread of execution.
    """

    def __init__(
        self,
        *,
        project_name: str | None = None,
        argv: list[str] | None = None,
        cwd: str | Path | None = None,
        policy: Policy | None = None,
        metadata: dict[str, Any] | None = None,
        out_path: str | Path | None = None,
    ) -> None:
        self.policy = policy or Policy()
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.out_path = Path(out_path) if out_path else None
        self.run_id = str(uuid.uuid4())
        self.steps: list[dict[str, Any]] = []
        self.metadata, metadata_redactions = redact(metadata or {})
        self.redactions = _qualify_redactions(metadata_redactions, "/metadata")

        revision = _git(["rev-parse", "HEAD"], self.cwd)
        dirty = _git(["status", "--porcelain"], self.cwd)
        self.project = {
            "name": project_name or self.cwd.name,
            "revision": revision,
            "dirty": None if dirty is None else bool(dirty),
        }
        self.invocation = {
            "argv": list(argv or sys.argv),
            "cwd": str(self.cwd),
            "env_keys": sorted(os.environ),
            "python": platform.python_version(),
        }
        self.actor = {
            "type": "human+agent",
            "name": getpass.getuser(),
            "version": PACKAGE_VERSION,
        }

    def __enter__(self) -> RunRecorder:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.out_path is not None:
            self.finalize()

    @contextmanager
    def step(
        self,
        kind: str,
        name: str,
        *,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        if kind not in STEP_KINDS:
            raise ValueError(f"invalid step kind {kind!r}; expected one of {sorted(STEP_KINDS)}")
        # Serializing here validates the input before any user code runs (a
        # failure in the finally block would mask in-flight exceptions) and
        # freezes a snapshot, so mutating the passed object during the step
        # cannot alter the recorded evidence.
        try:
            frozen_input = canonical_json(input)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"step input must be strict-JSON-serializable (no NaN/Infinity): {exc}"
            ) from exc
        started_at = utc_now()
        handle: dict[str, Any] = {
            "output": None,
            "status": "ok",
            "error": None,
            "cost": None,
            "metadata": dict(metadata or {}),
        }
        try:
            yield handle
        except Exception as exc:
            handle["status"] = "error"
            handle["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            ended_at = utc_now()
            step_index = len(self.steps)
            step_base = f"/steps/{step_index}"
            redacted_input, input_redactions = redact(json.loads(frozen_input))
            redacted_output, output_redactions = redact(handle.get("output"))
            redacted_cost, cost_redactions = redact(handle.get("cost"))
            redacted_metadata, metadata_redactions = redact(handle.get("metadata") or {})
            step = {
                "step_id": f"step-{step_index + 1}",
                "kind": kind,
                "name": name,
                "status": handle.get("status", "ok"),
                "started_at": started_at,
                "ended_at": ended_at,
                "input": redacted_input,
                "output": redacted_output,
                "error": handle.get("error"),
                "cost": redacted_cost,
                "metadata": redacted_metadata,
                "input_digest": None if input is None else sha256_json(redacted_input),
                "output_digest": (
                    None if handle.get("output") is None else sha256_json(redacted_output)
                ),
            }
            self.steps.append(step)
            self.redactions.extend(_qualify_redactions(input_redactions, f"{step_base}/input"))
            self.redactions.extend(_qualify_redactions(output_redactions, f"{step_base}/output"))
            self.redactions.extend(_qualify_redactions(cost_redactions, f"{step_base}/cost"))
            self.redactions.extend(
                _qualify_redactions(metadata_redactions, f"{step_base}/metadata")
            )

    def finalize(self, path: str | Path | None = None) -> dict[str, Any]:
        bundle = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": utc_now(),
            "actor": self.actor,
            "project": self.project,
            "invocation": self.invocation,
            "steps": self.steps,
            "redactions": sorted(set(self.redactions)),
            "metadata": self.metadata,
        }
        bundle["bundle_digest"] = stable_digest(bundle)
        target = Path(path) if path else self.out_path
        if target is not None:
            self.policy.check_write_path(target)
            write_bundle(target, bundle)
        return bundle
