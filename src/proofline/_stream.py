"""Step lifecycle for streamed provider calls, sync and async.

Invariant: the model step is always recorded exactly once, whatever happens to
the stream. A failed request records an error step; a fully consumed stream
records ``truncated: false``; an abandoned or interrupted stream records the
text received so far with ``truncated: true``.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from .recorder import RunRecorder


def _stream_output(chunks: list[str], completed: bool) -> dict[str, Any]:
    return {
        "streamed": True,
        "truncated": not completed,
        "content": "".join(chunks),
        "chunks": list(chunks),
    }


def record_streamed_call(
    recorder: RunRecorder,
    name: str,
    request: dict[str, Any],
    create: Callable[[], Any],
    extract_text: Callable[[Any], str | None],
    model: Any,
) -> Iterator[Any]:
    step = recorder.step("model", name, input=request)
    handle = step.__enter__()
    handle["metadata"]["model"] = model
    try:
        stream = create()
    except BaseException as exc:
        step.__exit__(type(exc), exc, exc.__traceback__)
        raise
    return _replay(stream, handle, step, extract_text)


def _replay(
    stream: Any,
    handle: dict[str, Any],
    step: Any,
    extract_text: Callable[[Any], str | None],
) -> Iterator[Any]:
    chunks: list[str] = []
    completed = False
    try:
        for event in stream:
            text = extract_text(event)
            if text:
                chunks.append(text)
            yield event
        completed = True
    finally:
        handle["output"] = _stream_output(chunks, completed)
        step.__exit__(*sys.exc_info())


async def record_streamed_call_async(
    recorder: RunRecorder,
    name: str,
    request: dict[str, Any],
    create: Callable[[], Any],
    extract_text: Callable[[Any], str | None],
    model: Any,
) -> AsyncIterator[Any]:
    step = recorder.step("model", name, input=request)
    handle = step.__enter__()
    handle["metadata"]["model"] = model
    try:
        stream = await create()
    except BaseException as exc:
        step.__exit__(type(exc), exc, exc.__traceback__)
        raise
    return _replay_async(stream, handle, step, extract_text)


async def _replay_async(
    stream: Any,
    handle: dict[str, Any],
    step: Any,
    extract_text: Callable[[Any], str | None],
) -> AsyncIterator[Any]:
    chunks: list[str] = []
    completed = False
    try:
        async for event in stream:
            text = extract_text(event)
            if text:
                chunks.append(text)
            yield event
        completed = True
    finally:
        handle["output"] = _stream_output(chunks, completed)
        step.__exit__(*sys.exc_info())
