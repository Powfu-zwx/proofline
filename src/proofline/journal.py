"""Crash-safe journals for run bundles.

A journal is an append-only JSONL sidecar written while a run is in flight.
Every completed step is appended — and fsynced — the moment it finishes, so a
process that dies mid-run loses at most the step it was executing. The bundle
is then rebuilt from whatever reached disk:

    proofline recover run.json.journal

The rebuilt bundle is sealed exactly like a live ``finalize()`` would have
sealed it (same stable digest over the same canonical JSON). Journal mode
also keeps step payloads on disk instead of accumulating them in memory, so
recording a long run costs the memory of one step, not of the whole run.

Guarantees and limits:

- Completed steps are durable when ``step()`` returns (flush + fsync).
- An in-flight step that never completes is not recorded — same as memory mode.
- A torn final line (crash mid-append) is detected and dropped; a corrupt
  line followed by further records is a hard error, because silent loss in
  the middle would forge evidence.
- Recovery trusts the journal as recorded: steps are already redacted and
  carry their digests; ``verify`` re-checks everything as usual.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model import SCHEMA_VERSION, VOLATILE_TOP_LEVEL, StableDigestBuilder
from .storage import write_bundle

JOURNAL_MARKER = "proofline-journal"
JOURNAL_VERSION = 1
JOURNAL_SUFFIX = ".journal"

_REQUIRED_RUN_FIELDS = ("run_id", "actor", "project", "invocation")


class JournalError(ValueError):
    """The journal is corrupt or not a proofline journal."""


class JournalWriter:
    """Append-only JSONL journal writer; every append is flushed and fsynced."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")

    @property
    def closed(self) -> bool:
        return self._handle.closed

    def _append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        self._handle.write(line + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def write_header(self, header: dict[str, Any]) -> None:
        self._append({**header, "j": JOURNAL_MARKER, "v": JOURNAL_VERSION})

    def append_step(self, step: dict[str, Any], redactions: list[str]) -> None:
        self._append({"t": "step", "step": step, "redactions": redactions})

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def discard(self) -> None:
        self.close()
        self.path.unlink(missing_ok=True)


def default_bundle_path(journal_path: str | Path) -> Path:
    """Where ``recover`` writes by default: ``run.json.journal`` -> ``run.json``."""
    name = str(journal_path)
    if name.endswith(JOURNAL_SUFFIX):
        return Path(name[: -len(JOURNAL_SUFFIX)])
    return Path(f"{name}.run.json")


def read_journal(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse a journal into (header, step records); a torn final line is dropped."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            trailing = any(later.strip() for later in lines[index + 1 :])
            if trailing:
                raise JournalError(f"journal line {index + 1} is corrupt: {path}") from None
            break  # torn tail: the run died mid-append
        if not isinstance(record, dict):
            raise JournalError(f"journal line {index + 1} is not an object: {path}")
        records.append(record)

    if not records or records[0].get("j") != JOURNAL_MARKER:
        raise JournalError(f"not a proofline journal (missing header): {path}")
    header = records[0]
    if header.get("v") != JOURNAL_VERSION:
        raise JournalError(f"unsupported journal version {header.get('v')!r}: {path}")
    run = header.get("run")
    if not isinstance(run, dict):
        raise JournalError(f"journal header has no run record: {path}")
    missing = [field for field in _REQUIRED_RUN_FIELDS if field not in run]
    if "created_at" not in header:
        missing.append("created_at")
    if missing:
        raise JournalError(f"journal header is missing fields: {', '.join(missing)}")

    steps: list[dict[str, Any]] = []
    for record in records[1:]:
        if record.get("t") != "step" or not isinstance(record.get("step"), dict):
            raise JournalError(f"unexpected journal record: {str(record)[:120]}")
        steps.append(record)
    return header, steps


def bundle_from_journal(path: str | Path) -> dict[str, Any]:
    """Rebuild the sealed bundle dict from a journal; nothing is written."""
    header, records = read_journal(path)
    run = header["run"]
    redactions: set[str] = set(run.get("metadata_redactions") or [])
    steps: list[dict[str, Any]] = []
    for record in records:
        step = record["step"]
        steps.append(step)
        redactions.update(record.get("redactions") or [])
    bundle: dict[str, Any] = {
        "schema_version": run.get("schema_version", SCHEMA_VERSION),
        "run_id": run["run_id"],
        "created_at": header["created_at"],
        "actor": run["actor"],
        "project": run["project"],
        "invocation": run["invocation"],
        "steps": steps,
        "redactions": sorted(redactions),
        "metadata": run.get("metadata", {}),
    }
    builder = StableDigestBuilder(
        {
            key: value
            for key, value in bundle.items()
            if key not in VOLATILE_TOP_LEVEL and key != "steps"
        }
    )
    for step in steps:
        builder.add_step(step)
    bundle["bundle_digest"] = builder.hexdigest()
    return bundle


def recover(journal_path: str | Path, out_path: str | Path | None = None) -> dict[str, Any]:
    """Rebuild the bundle from a crash journal, write it, and remove the journal.

    The journal is only removed after the bundle write succeeded, so a failed
    write never destroys the remaining evidence.
    """
    bundle = bundle_from_journal(journal_path)
    target = Path(out_path) if out_path is not None else default_bundle_path(journal_path)
    write_bundle(target, bundle)
    Path(journal_path).unlink(missing_ok=True)
    return bundle
