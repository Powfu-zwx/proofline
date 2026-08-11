from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
# "token" stays singular: plural keys such as "max_tokens" or "total_tokens" are counts.
SECRET_KEY = re.compile(
    r"(?i)(^|[_\-.])"
    r"(api[_-]?keys?|auth|token|secrets?|passwords?|authorization|credentials?|private[_-]?keys?)"
    r"(?=$|[_\-.])"
)
SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"
    r"|Bearer\s+[A-Za-z0-9._-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def _escape_pointer(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def redact(value: Any) -> tuple[Any, list[str]]:
    redactions: list[str] = []

    def walk(node: Any, pointer: str) -> Any:
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for key, child in node.items():
                child_pointer = f"{pointer}/{_escape_pointer(str(key))}"
                if SECRET_KEY.search(str(key)) and child is not None:
                    result[key] = REDACTED
                    redactions.append(child_pointer)
                else:
                    result[key] = walk(child, child_pointer)
            return result
        if isinstance(node, list):
            return [walk(child, f"{pointer}/{index}") for index, child in enumerate(node)]
        if isinstance(node, str) and SECRET_VALUE.search(node):
            redactions.append(pointer or "/")
            return REDACTED
        return node

    return walk(value, ""), redactions


def contains_unredacted_secret(value: Any, pointer: str = "") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{_escape_pointer(str(key))}"
            if SECRET_KEY.search(str(key)) and child is not None and child != REDACTED:
                leaks.append(child_pointer)
            leaks.extend(contains_unredacted_secret(child, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(contains_unredacted_secret(child, f"{pointer}/{index}"))
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        leaks.append(pointer or "/")
    return leaks
