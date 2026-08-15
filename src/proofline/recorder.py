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

from .journal import JOURNAL_SUFFIX, JournalWriter, bundle_from_journal
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


def _journal_path(
    journal: bool | str | Path | None, out_path: str | Path | None
) -> Path | None:
    if journal is None or journal is False:
        return None
    if journal is True:
        if out_path is None:
            raise ValueError(
                "journal=True requires out_path; the journal is written next to the bundle"
            )
        return Path(f"{out_path}{JOURNAL_SUFFIX}")
    return Path(journal)


class RunRecorder:
    """Record one bounded execution as a verifiable run bundle.

    Steps are recorded with :meth:`step`; :meth:`finalize` seals the bundle
    with its stable digest and optionally writes it. Instances are not
    thread-safe: use one recorder per thread of execution.

    With ``journal=`` set, every completed step is appended (and fsynced) to
    a crash journal instead of being held in memory; a process that dies
    mid-run can be rebuilt with :func:`proofline.journal.recover`. Step
    payloads then live on disk, so memory stays bounded by the largest step.
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
        journal: bool | str | Path | None = None,
    ) -> None:
        self.policy = policy or Policy()
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.out_path = Path(out_path) if out_path else None
        self.run_id = str(uuid.uuid4())
        self.steps: list[dict[str, Any]] = []
        self._step_count = 0
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
        self._journal: JournalWriter | None = None
        journal_target = _journal_path(journal, out_path)
        if journal_target is not None:
            self.policy.check_write_path(journal_target)
            self._journal = JournalWriter(journal_target)
            self._journal.write_header(
                {
                    "created_at": utc_now(),
                    "run": {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": self.run_id,
                        "actor": self.actor,
                        "project": self.project,
                        "invocation": self.invocation,
                        "metadata": self.metadata,
                        "metadata_redactions": self.redactions,
                    },
                }
            )

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
        if self._journal is not None and self._journal.closed:
            raise RuntimeError(
                "cannot record steps after finalize(); the journal is closed — "
                "recover the journal or start a new recorder"
            )
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
            step_index = self._step_count
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
            step_redactions = [
                *_qualify_redactions(input_redactions, f"{step_base}/input"),
                *_qualify_redactions(output_redactions, f"{step_base}/output"),
                *_qualify_redactions(cost_redactions, f"{step_base}/cost"),
                *_qualify_redactions(metadata_redactions, f"{step_base}/metadata"),
            ]
            if self._journal is not None:
                self._journal.append_step(step, step_redactions)
            else:
                self.steps.append(step)
            self._step_count += 1
            self.redactions.extend(step_redactions)

    def finalize(self, path: str | Path | None = None) -> dict[str, Any]:
        if self._journal is not None:
            return self._finalize_journaled(path)
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

    def _finalize_journaled(self, path: str | Path | None) -> dict[str, Any]:
        """Rebuild the bundle from the journal; the journal only dies after a write."""
        target = Path(path) if path else self.out_path
        self._journal.close()
        bundle = bundle_from_journal(self._journal.path)
        if target is not None:
            self.policy.check_write_path(target)
            write_bundle(target, bundle)
            self._journal.discard()
        return bundle
