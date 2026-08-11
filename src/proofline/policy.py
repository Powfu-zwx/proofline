from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Policy:
    allow_shell: bool = True
    allow_network: bool = True
    allowed_write_roots: tuple[Path, ...] = field(default_factory=tuple)

    def check_command(self, argv: list[str]) -> None:
        if not argv:
            raise PolicyViolation("empty command")
        if not self.allow_shell:
            raise PolicyViolation("shell execution is disabled by policy")

    def check_network(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and not self.allow_network:
            raise PolicyViolation(f"network access is disabled by policy: {url}")

    def check_write_path(self, path: str | Path) -> None:
        if not self.allowed_write_roots:
            return
        target = Path(path).resolve()
        if not any(target.is_relative_to(root.resolve()) for root in self.allowed_write_roots):
            raise PolicyViolation(f"write path is outside allowed roots: {target}")
