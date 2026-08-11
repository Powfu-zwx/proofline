"""Optional Anthropic SDK integration. Requires ``pip install proofline[anthropic]``.

Wraps both ``anthropic.Anthropic`` and ``anthropic.AsyncAnthropic`` clients.
Only ``messages.create`` calls are recorded, including ``stream=True`` event
iteration; the ``messages.stream()`` helper and other client surfaces are
delegated to the wrapped client unrecorded.
"""

from __future__ import annotations

import inspect
from typing import Any

from ._stream import record_streamed_call, record_streamed_call_async
from .recorder import RunRecorder


class ProoflineAnthropic:
    """Wrap an Anthropic client so each message call is recorded as a model step."""

    def __init__(self, client: Any, recorder: RunRecorder) -> None:
        self._client = client
        self.messages = _MessagesProxy(client.messages, recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _event_text(event: Any) -> str | None:
    delta = getattr(event, "delta", None)
    text = getattr(delta, "text", None)
    return text if isinstance(text, str) else None


def _usage_cost(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
    }


class _MessagesProxy:
    def __init__(self, messages: Any, recorder: RunRecorder) -> None:
        self._messages = messages
        self._recorder = recorder
        self._is_async = inspect.iscoroutinefunction(messages.create)

    def create(self, **kwargs: Any) -> Any:
        if self._is_async:
            return self._create_async(**kwargs)
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
            handle["cost"] = _usage_cost(response)
            return response

    async def _create_async(self, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        if kwargs.get("stream"):
            return await record_streamed_call_async(
                self._recorder,
                "messages.create",
                kwargs,
                lambda: self._messages.create(**kwargs),
                _event_text,
                model,
            )
        with self._recorder.step("model", "messages.create", input=kwargs) as handle:
            handle["metadata"]["model"] = model
            response = await self._messages.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            handle["cost"] = _usage_cost(response)
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._messages, name)


def wrap(client: Any, recorder: RunRecorder) -> ProoflineAnthropic:
    """Return a recorder-backed wrapper around an Anthropic or AsyncAnthropic client."""
    return ProoflineAnthropic(client, recorder)
