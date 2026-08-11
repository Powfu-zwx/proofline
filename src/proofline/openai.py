"""Optional OpenAI SDK integration. Requires ``pip install proofline[openai]``."""

from __future__ import annotations

from typing import Any

from .recorder import RunRecorder


class ProoflineOpenAI:
    """Wrap an ``openai.OpenAI`` client so each chat completion is recorded as a model step."""

    def __init__(self, client: Any, recorder: RunRecorder) -> None:
        self._client = client
        self._recorder = recorder
        self.chat = _ChatProxy(client.chat, recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _ChatProxy:
    def __init__(self, chat: Any, recorder: RunRecorder) -> None:
        self._chat = chat
        self.completions = _CompletionsProxy(chat.completions, recorder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class _CompletionsProxy:
    def __init__(self, completions: Any, recorder: RunRecorder) -> None:
        self._completions = completions
        self._recorder = recorder

    def create(self, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        if kwargs.get("stream"):
            return self._create_stream(kwargs, model)
        with self._recorder.step("model", "chat.completions.create", input=kwargs) as handle:
            response = self._completions.create(**kwargs)
            handle["output"] = response.model_dump(mode="json")
            usage = getattr(response, "usage", None)
            if usage is not None:
                handle["cost"] = {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
            handle["metadata"]["model"] = model
            return response

    def _create_stream(self, kwargs: dict[str, Any], model: Any) -> Any:
        recorder_step = self._recorder.step("model", "chat.completions.create", input=kwargs)
        handle = recorder_step.__enter__()
        try:
            stream = self._completions.create(**kwargs)
        except BaseException:
            recorder_step.__exit__(None, None, None)
            raise
        return self._wrap_stream(stream, handle, model, recorder_step)

    def _wrap_stream(self, stream: Any, handle: dict[str, Any], model: Any, step: Any) -> Any:
        chunks: list[str] = []
        try:
            for chunk in stream:
                choices = getattr(chunk, "choices", None)
                if choices:
                    content = getattr(choices[0].delta, "content", None)
                    if content:
                        chunks.append(content)
                yield chunk
            handle["output"] = {"streamed": True, "content": "".join(chunks)}
            handle["metadata"]["model"] = model
        except BaseException as exc:
            handle["output"] = {"streamed": True, "content": "".join(chunks)}
            handle["metadata"]["model"] = model
            step.__exit__(type(exc), exc, exc.__traceback__)
            return
        step.__exit__(None, None, None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


def wrap(client: Any, recorder: RunRecorder) -> ProoflineOpenAI:
    """Return a recorder-backed wrapper around an ``openai.OpenAI`` client."""
    return ProoflineOpenAI(client, recorder)
