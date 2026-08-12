"""Serve recorded model responses so a bundle doubles as a test fixture.

A wrapped client with a :class:`ReplaySource` never calls the provider: model
steps are answered from the baseline bundle while the run is recorded as
usual. Replaying a baseline through changed code and diffing the two bundles
isolates code-caused behavior changes from model drift.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import AsyncIterator, Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .diff import _diff
from .model import sha256_json
from .redact import redact
from .storage import read_bundle

REPLAY_ENV = "PROOFLINE_REPLAY"


class ReplayMismatch(RuntimeError):
    """The live request has no matching recorded step to serve."""


class ReplayedView:
    """Read-only attribute and item access over a recorded JSON value."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            return view(self._data[name])
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, key: Any) -> Any:
        return view(self._data[key])

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return deepcopy(self._data)

    def __repr__(self) -> str:
        return f"ReplayedView({self._data!r})"


def view(value: Any) -> Any:
    """Wrap recorded JSON so provider-shaped attribute access works on it."""
    if isinstance(value, dict):
        return ReplayedView(value)
    if isinstance(value, list):
        return [view(item) for item in value]
    return value


async def aiter_chunks(chunks: Iterable[Any]) -> AsyncIterator[Any]:
    for chunk in chunks:
        yield chunk


class ReplaySource:
    """Serve recorded model-step outputs from a baseline bundle.

    ``strategy="strict"`` matches each request by step name and
    redacted-input digest and fails fast on any divergence; use it as a pure
    fixture. ``strategy="ordered"`` serves the next recorded step with the
    same name regardless of the request, so a changed pipeline still
    completes; use it for attribution diffs. Each recorded step is served at
    most once. Instances are not thread-safe.
    """

    def __init__(
        self,
        bundle_or_path: str | Path | dict[str, Any],
        *,
        strategy: str = "strict",
    ) -> None:
        if strategy not in {"strict", "ordered"}:
            raise ValueError(f"unknown replay strategy {strategy!r}; use 'strict' or 'ordered'")
        if isinstance(bundle_or_path, (str, Path)):
            bundle = read_bundle(bundle_or_path)
        else:
            bundle = bundle_or_path
        self.strategy = strategy
        self._steps: deque[dict[str, Any]] = deque(
            step for step in bundle.get("steps", []) if step.get("kind") == "model"
        )

    def remaining(self) -> int:
        return len(self._steps)

    def _take_strict(self, name: str, request: dict[str, Any]) -> dict[str, Any]:
        redacted_request, _ = redact(request)
        digest = sha256_json(redacted_request)
        for step in self._steps:
            if step.get("name") == name and step.get("input_digest") == digest:
                self._steps.remove(step)
                return step
        for step in self._steps:
            if step.get("name") == name:
                divergence = "; ".join(_diff(step.get("input"), redacted_request)[:5])
                raise ReplayMismatch(
                    f"no recorded {name!r} step matches the request "
                    f"(closest remaining step {step.get('step_id')} differs: {divergence})"
                )
        raise ReplayMismatch(f"no recorded {name!r} step remaining")

    def _take_ordered(self, name: str) -> dict[str, Any]:
        for step in self._steps:
            if step.get("name") == name:
                self._steps.remove(step)
                return step
        raise ReplayMismatch(f"no recorded {name!r} step remaining")

    def _take(self, name: str, request: dict[str, Any]) -> dict[str, Any]:
        if self.strategy == "strict":
            step = self._take_strict(name, request)
        else:
            step = self._take_ordered(name)
        if step.get("output") is None:
            raise ReplayMismatch(
                f"recorded step {step.get('step_id')} has no output "
                f"(status={step.get('status')!r}); it cannot be replayed"
            )
        return step

    def serve(self, name: str, request: dict[str, Any]) -> Any:
        """Return the recorded response for a non-streamed call."""
        step = self._take(name, request)
        output = step["output"]
        if isinstance(output, dict) and output.get("streamed"):
            raise ReplayMismatch(
                f"recorded step {step.get('step_id')} was streamed; "
                "the live call requested a non-streamed response"
            )
        return view(deepcopy(output))

    def serve_stream(self, name: str, request: dict[str, Any]) -> list[str]:
        """Return the recorded text chunks for a streamed call."""
        step = self._take(name, request)
        output = step["output"]
        if not (isinstance(output, dict) and output.get("streamed")):
            raise ReplayMismatch(
                f"recorded step {step.get('step_id')} was not streamed; "
                "the live call requested a stream"
            )
        chunks = output.get("chunks")
        if chunks is None:
            # Bundles recorded before chunk capture replay as one piece.
            content = output.get("content", "")
            chunks = [content] if content else []
        return list(chunks)


def resolve_replay(
    explicit: ReplaySource | str | Path | dict[str, Any] | None,
) -> ReplaySource | None:
    """Turn a wrap() replay argument or the PROOFLINE_REPLAY env var into a source."""
    if explicit is None:
        env_path = os.environ.get(REPLAY_ENV)
        return ReplaySource(env_path) if env_path else None
    if isinstance(explicit, ReplaySource):
        return explicit
    return ReplaySource(explicit)
