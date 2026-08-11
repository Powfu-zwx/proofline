"""Optional OpenAI SDK integration. Requires ``pip install proofline[openai]``.

Wraps both ``openai.OpenAI`` and ``openai.AsyncOpenAI`` clients. Only
``chat.completions.create`` calls are recorded; other client surfaces are
delegated to the wrapped client unrecorded.
"""

from __future__ import annotations

import inspect
from typing import Any

from ._stream import record_streamed_call, record_streamed_call_async
from .recorder import RunRecorder


class ProoflineOpenAI:
    """Wrap an OpenAI client so each chat completion is recorded as a model step."""

    def __init__(self, client: Any, recorder: RunRecorder) -> None:
        self._client = client
        self.chat = _ChatProxy(client.chat, recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _ChatProxy:
    def __init__(self, chat: Any, recorder: RunRecorder) -> None:
        self._chat = chat
        self.completions = _CompletionsProxy(chat.completions, recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


def _chunk_text(chunk: Any) -> str | None:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None)


def _usage_cost(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


class _CompletionsProxy:
    def __init__(self, completions: Any, recorder: RunRecorder) -> None:
        self._completions = completions
        self._recorder = recorder
        self._is_async = inspect.iscoroutinefunction(completions.create)

    def create(self, **kwargs: Any) -> Any:
        if self._is_async:
            return self._create_async(**kwargs)
        model = kwargs.get("model")
        if kwargs.get("stream"):
            return record_streamed_call(
                self._recorder,
                "chat.completions.create",
                kwargs,
                lambda: self._completions.create(**kwargs),
                _chunk_text,
                model,
            )
        with self._recorder.step("model", "chat.completions.create", input=kwargs) as handle:
            handle["metadata"]["model"] = model
            response = self._completions.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            handle["cost"] = _usage_cost(response)
            return response

    async def _create_async(self, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        if kwargs.get("stream"):
            return await record_streamed_call_async(
                self._recorder,
                "chat.completions.create",
                kwargs,
                lambda: self._completions.create(**kwargs),
                _chunk_text,
                model,
            )
        with self._recorder.step("model", "chat.completions.create", input=kwargs) as handle:
            handle["metadata"]["model"] = model
            response = await self._completions.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            handle["cost"] = _usage_cost(response)
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


def wrap(client: Any, recorder: RunRecorder) -> ProoflineOpenAI:
    """Return a recorder-backed wrapper around an OpenAI or AsyncOpenAI client."""
    return ProoflineOpenAI(client, recorder)
