"""Optional OpenAI SDK integration. Requires ``pip install proofline[openai]``.

Wraps both ``openai.OpenAI`` and ``openai.AsyncOpenAI`` clients. Only
``chat.completions.create`` calls are recorded; other client surfaces are
delegated to the wrapped client unrecorded. Pass ``replay=`` (or set
``PROOFLINE_REPLAY``) to serve responses from a baseline bundle instead of
calling the provider; see ``docs/replay.md``.
"""

from __future__ import annotations

import inspect
from typing import Any

from ._stream import record_streamed_call, record_streamed_call_async
from .recorder import RunRecorder
from .replay import ReplaySource, aiter_chunks, resolve_replay, view

_STEP_NAME = "chat.completions.create"


class ProoflineOpenAI:
    """Wrap an OpenAI client so each chat completion is recorded as a model step."""

    def __init__(
        self,
        client: Any,
        recorder: RunRecorder,
        replay: ReplaySource | None = None,
    ) -> None:
        self._client = client
        self.chat = _ChatProxy(client.chat, recorder, replay)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _ChatProxy:
    def __init__(self, chat: Any, recorder: RunRecorder, replay: ReplaySource | None) -> None:
        self._chat = chat
        self.completions = _CompletionsProxy(chat.completions, recorder, replay)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


def _chunk_text(chunk: Any) -> str | None:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None)


def _replay_chunk(piece: str) -> Any:
    return view({"choices": [{"delta": {"content": piece}}]})


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
    def __init__(
        self,
        completions: Any,
        recorder: RunRecorder,
        replay: ReplaySource | None,
    ) -> None:
        self._completions = completions
        self._recorder = recorder
        self._replay = replay
        self._is_async = inspect.iscoroutinefunction(completions.create)

    def create(self, **kwargs: Any) -> Any:
        if self._is_async:
            return self._create_async(**kwargs)
        model = kwargs.get("model")
        if kwargs.get("stream"):

            def create_stream() -> Any:
                if self._replay is not None:
                    pieces = self._replay.serve_stream(_STEP_NAME, kwargs)
                    return [_replay_chunk(piece) for piece in pieces]
                return self._completions.create(**kwargs)

            return record_streamed_call(
                self._recorder, _STEP_NAME, kwargs, create_stream, _chunk_text, model
            )
        with self._recorder.step("model", _STEP_NAME, input=kwargs) as handle:
            handle["metadata"]["model"] = model
            if self._replay is not None:
                response = self._replay.serve(_STEP_NAME, kwargs)
            else:
                response = self._completions.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            handle["cost"] = _usage_cost(response)
            return response

    async def _create_async(self, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        if kwargs.get("stream"):

            async def create_stream() -> Any:
                if self._replay is not None:
                    pieces = self._replay.serve_stream(_STEP_NAME, kwargs)
                    return aiter_chunks([_replay_chunk(piece) for piece in pieces])
                return await self._completions.create(**kwargs)

            return await record_streamed_call_async(
                self._recorder, _STEP_NAME, kwargs, create_stream, _chunk_text, model
            )
        with self._recorder.step("model", _STEP_NAME, input=kwargs) as handle:
            handle["metadata"]["model"] = model
            if self._replay is not None:
                response = self._replay.serve(_STEP_NAME, kwargs)
            else:
                response = await self._completions.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            handle["cost"] = _usage_cost(response)
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


def wrap(
    client: Any,
    recorder: RunRecorder,
    *,
    replay: ReplaySource | str | None = None,
) -> ProoflineOpenAI:
    """Return a recorder-backed wrapper around an OpenAI or AsyncOpenAI client.

    With ``replay`` (or the ``PROOFLINE_REPLAY`` environment variable) set,
    responses are served from the given baseline bundle instead of the
    provider, while the run is still recorded.
    """
    return ProoflineOpenAI(client, recorder, resolve_replay(replay))
