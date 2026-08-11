from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import stable_bundle
from .storage import read_bundle


DERIVED_STEP_FIELDS = {"input_digest", "output_digest"}


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
        differences = []
        if len(left) != len(right):
            differences.append(f"{display_path}: length {len(left)} != {len(right)}")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(_diff(left_item, right_item, f"{display_path}[{index}]"))
        return differences
    if left != right:
        return [f"{display_path}: {left!r} != {right!r}"]
    return []
