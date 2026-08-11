from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Policy:
    allowed_write_roots: tuple[Path, ...] = ()

    def check_write_path(self, path: str | Path) -> None:
        if not self.allowed_write_roots:
            return
        target = Path(path).resolve()
        if not any(target.is_relative_to(root.resolve()) for root in self.allowed_write_roots):
            raise PolicyViolation(f"write path is outside allowed roots: {target}")
