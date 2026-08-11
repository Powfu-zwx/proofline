"""Optional OpenAI SDK integration. Requires ``pip install proofline[openai]``.

Only ``chat.completions.create`` calls are recorded; other client surfaces are
delegated to the wrapped client unrecorded.
"""

from __future__ import annotations

from typing import Any

from ._stream import record_streamed_call
from .recorder import RunRecorder


class ProoflineOpenAI:
    """Wrap an ``openai.OpenAI`` client so each chat completion is recorded as a model step."""

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


class _CompletionsProxy:
    def __init__(self, completions: Any, recorder: RunRecorder) -> None:
        self._completions = completions
        self._recorder = recorder

    def create(self, **kwargs: Any) -> Any:
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
            usage = getattr(response, "usage", None)
            if usage is not None:
                handle["cost"] = {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


def wrap(client: Any, recorder: RunRecorder) -> ProoflineOpenAI:
    """Return a recorder-backed wrapper around an ``openai.OpenAI`` client."""
    return ProoflineOpenAI(client, recorder)
