from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_bundle(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_bundle(path: str | Path, bundle: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    serialized = json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False)
    temporary.write_text(serialized + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
