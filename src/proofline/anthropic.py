"""Optional Anthropic SDK integration. Requires ``pip install proofline[anthropic]``.

Wraps both ``anthropic.Anthropic`` and ``anthropic.AsyncAnthropic`` clients.
Only ``messages.create`` calls are recorded, including ``stream=True`` event
iteration; the ``messages.stream()`` helper and other client surfaces are
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

_STEP_NAME = "messages.create"


class ProoflineAnthropic:
    """Wrap an Anthropic client so each message call is recorded as a model step."""

    def __init__(
        self,
        client: Any,
        recorder: RunRecorder,
        replay: ReplaySource | None = None,
    ) -> None:
        self._client = client
        self.messages = _MessagesProxy(client.messages, recorder, replay)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _event_text(event: Any) -> str | None:
    delta = getattr(event, "delta", None)
    text = getattr(delta, "text", None)
    return text if isinstance(text, str) else None


def _replay_chunk(piece: str) -> Any:
    return view({"type": "content_block_delta", "delta": {"text": piece}})


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
    def __init__(
        self,
        messages: Any,
        recorder: RunRecorder,
        replay: ReplaySource | None,
    ) -> None:
        self._messages = messages
        self._recorder = recorder
        self._replay = replay
        self._is_async = inspect.iscoroutinefunction(messages.create)

    def create(self, **kwargs: Any) -> Any:
        if self._is_async:
            return self._create_async(**kwargs)
        model = kwargs.get("model")
        if kwargs.get("stream"):

            def create_stream() -> Any:
                if self._replay is not None:
                    pieces = self._replay.serve_stream(_STEP_NAME, kwargs)
                    return [_replay_chunk(piece) for piece in pieces]
                return self._messages.create(**kwargs)

            return record_streamed_call(
                self._recorder, _STEP_NAME, kwargs, create_stream, _event_text, model
            )
        with self._recorder.step("model", _STEP_NAME, input=kwargs) as handle:
            handle["metadata"]["model"] = model
            if self._replay is not None:
                response = self._replay.serve(_STEP_NAME, kwargs)
            else:
                response = self._messages.create(**kwargs)
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
                return await self._messages.create(**kwargs)

            return await record_streamed_call_async(
                self._recorder, _STEP_NAME, kwargs, create_stream, _event_text, model
            )
        with self._recorder.step("model", _STEP_NAME, input=kwargs) as handle:
            handle["metadata"]["model"] = model
            if self._replay is not None:
                response = self._replay.serve(_STEP_NAME, kwargs)
            else:
                response = await self._messages.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            handle["cost"] = _usage_cost(response)
            return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._messages, name)


def wrap(
    client: Any,
    recorder: RunRecorder,
    *,
    replay: ReplaySource | str | None = None,
) -> ProoflineAnthropic:
    """Return a recorder-backed wrapper around an Anthropic or AsyncAnthropic client.

    With ``replay`` (or the ``PROOFLINE_REPLAY`` environment variable) set,
    responses are served from the given baseline bundle instead of the
    provider, while the run is still recorded.
    """
    return ProoflineAnthropic(client, recorder, resolve_replay(replay))
