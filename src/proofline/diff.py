from __future__ import annotations

import difflib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .model import canonical_json, stable_bundle
from .storage import read_bundle

# input/output digests are computed from the payloads they sit next to; step_id
# is positional (step-3 just means "third recorded"). When alignment shifts
# positions, re-reporting every shifted step_id is noise on top of the
# added/removed lines that already describe the shift.
DERIVED_STEP_FIELDS = {"step_id", "input_digest", "output_digest"}
STEPS_PATH = "$.steps"


def diff_bundles(
    left: str | Path | dict[str, Any], right: str | Path | dict[str, Any]
) -> list[str]:
    left_bundle = read_bundle(left) if isinstance(left, (str, Path)) else left
    right_bundle = read_bundle(right) if isinstance(right, (str, Path)) else right
    return _diff(_semantic_bundle(left_bundle), _semantic_bundle(right_bundle))


def _semantic_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    semantic = stable_bundle(bundle)
    semantic["steps"] = [
        {key: value for key, value in step.items() if key not in DERIVED_STEP_FIELDS}
        for step in semantic.get("steps", [])
    ]
    return semantic


def _diff(left: Any, right: Any, path: str = "") -> list[str]:
    display_path = path or "$"
    if type(left) is not type(right):
        return [f"{display_path}: type {type(left).__name__} != {type(right).__name__}"]
    if isinstance(left, dict):
        differences: list[str] = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{display_path}.{key}"
            if key not in left:
                differences.append(f"{child_path}: missing in left")
            elif key not in right:
                differences.append(f"{child_path}: missing in right")
            else:
                differences.extend(_diff(left[key], right[key], child_path))
        return differences
    if isinstance(left, list):
        if display_path == STEPS_PATH:
            return _diff_steps(left, right, display_path)
        differences = []
        if len(left) != len(right):
            differences.append(f"{display_path}: length {len(left)} != {len(right)}")
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
            differences.extend(_diff(left_item, right_item, f"{display_path}[{index}]"))
        return differences
    if left != right:
        return [f"{display_path}: {left!r} != {right!r}"]
    return []


def _step_fingerprint(step: Any) -> str:
    """Deep-equality key for alignment; malformed steps still fingerprint."""
    try:
        return canonical_json(step)
    except (TypeError, ValueError):
        return repr(step)


def _step_identity(step: Any) -> tuple[str, str] | str:
    """The (kind, name) pair that decides whether two steps are the same step."""
    if isinstance(step, dict):
        return (str(step.get("kind")), str(step.get("name")))
    return _step_fingerprint(step)


def _step_label(step: Any) -> str:
    if not isinstance(step, dict):
        return f" ({type(step).__name__})"
    kind, name = step.get("kind"), step.get("name")
    if kind is None and name is None:
        return ""
    return f" ({kind}/{name})"


def _diff_steps(left: list[Any], right: list[Any], base: str) -> list[str]:
    """Align two step sequences, then pair same-identity steps for field diffs.

    Sequences are aligned by longest common subsequence of exactly equal
    steps, so an inserted or removed step reports once instead of shifting
    every following step out of alignment. Inside a changed region, a removed
    step pairs with the nearest added step of the same (kind, name) and
    reports field-level differences; the rest report as removed/added steps.
    Indices refer to the left bundle for removed and changed steps, and to
    the right bundle for added steps.
    """
    differences: list[str] = []
    if len(left) != len(right):
        differences.append(f"{base}: length {len(left)} != {len(right)}")
    if left == right:
        return differences
    matcher = difflib.SequenceMatcher(
        None,
        [_step_fingerprint(step) for step in left],
        [_step_fingerprint(step) for step in right],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        candidates: dict[Any, deque[int]] = defaultdict(deque)
        for j in range(j1, j2):
            candidates[_step_identity(right[j])].append(j)
        for i in range(i1, i2):
            queue = candidates.get(_step_identity(left[i]))
            if queue:
                j = queue.popleft()
                differences.extend(_diff(left[i], right[j], f"{base}[{i}]"))
            else:
                differences.append(f"{base}[{i}]: removed step{_step_label(left[i])}")
        for j in sorted(j for queue in candidates.values() for j in queue):
            differences.append(f"{base}[{j}]: added step{_step_label(right[j])}")
    return differences
