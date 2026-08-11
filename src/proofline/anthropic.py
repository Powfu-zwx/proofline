"""Optional Anthropic SDK integration. Requires ``pip install proofline[anthropic]``.

Only ``messages.create`` calls are recorded, including ``stream=True`` event
iteration; the ``messages.stream()`` helper and other client surfaces are
delegated to the wrapped client unrecorded.
"""

from __future__ import annotations

from typing import Any

from ._stream import record_streamed_call
from .recorder import RunRecorder


class ProoflineAnthropic:
    """Wrap an ``anthropic.Anthropic`` client so each message call is recorded as a model step."""

    def __init__(self, client: Any, recorder: RunRecorder) -> None:
        self._client = client
        self.messages = _MessagesProxy(client.messages, recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _event_text(event: Any) -> str | None:
    delta = getattr(event, "delta", None)
    text = getattr(delta, "text", None)
    return text if isinstance(text, str) else None


class _MessagesProxy:
    def __init__(self, messages: Any, recorder: RunRecorder) -> None:
        self._messages = messages
        self._recorder = recorder

    def create(self, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        if kwargs.get("stream"):
            return record_streamed_call(
                self._recorder,
                "messages.create",
                kwargs,
                lambda: self._messages.create(**kwargs),
                _event_text,
                model,
            )
        with self._recorder.step("model", "messages.create", input=kwargs) as handle:
            handle["metadata"]["model"] = model
            response = self._messages.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            usage = getattr(response, "usage", None)
            if usage is not None:
                handle["cost"] = {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens,
                }
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._messages, name)


def wrap(client: Any, recorder: RunRecorder) -> ProoflineAnthropic:
    """Return a recorder-backed wrapper around an ``anthropic.Anthropic`` client."""
    return ProoflineAnthropic(client, recorder)
