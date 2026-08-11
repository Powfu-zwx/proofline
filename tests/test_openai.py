from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from proofline import RunRecorder, verify_bundle
from proofline.openai import wrap


class _FakeResponse:
    def __init__(self) -> None:
        self.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def _fake_stream():
    for token in ("he", "llo"):
        delta = SimpleNamespace(content=token)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class OpenAIIntegrationTest(unittest.TestCase):
    def test_create_records_model_step_with_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            client = _FakeClient()
            recorder = RunRecorder(cwd=directory, argv=["demo"], out_path=out)
            wrapped = wrap(client, recorder)
            response = wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
            )
            self.assertEqual(response.model_dump()["choices"][0]["message"]["content"], "pong")

            bundle = recorder.finalize()
            step = bundle["steps"][0]
            self.assertEqual(step["kind"], "model")
            self.assertEqual(step["name"], "chat.completions.create")
            self.assertEqual(step["input"]["model"], "gpt-4o-mini")
            self.assertEqual(step["input"]["messages"][0]["content"], "ping")
            self.assertEqual(step["output"]["choices"][0]["message"]["content"], "pong")
            self.assertEqual(step["cost"]["total_tokens"], 18)
            self.assertEqual(step["metadata"]["model"], "gpt-4o-mini")
            self.assertEqual(verify_bundle(out), [])

    def test_stream_records_full_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.chat.completions.create = lambda **kwargs: _fake_stream()
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            stream = wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
            )
            collected = [chunk.choices[0].delta.content for chunk in stream]
            bundle = recorder.finalize()
            step = bundle["steps"][0]
            self.assertEqual("".join(collected), "hello")
            self.assertEqual(step["status"], "ok")
            self.assertEqual(step["output"]["content"], "hello")
            self.assertTrue(step["output"]["streamed"])
            self.assertFalse(step["output"]["truncated"])
            self.assertEqual(step["metadata"]["model"], "gpt-4o-mini")

    def test_stream_create_failure_records_error_step(self) -> None:
        def boom(**kwargs):
            raise RuntimeError("api down")

        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.chat.completions.create = boom
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            with self.assertRaises(RuntimeError):
                wrapped.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True)
            step = recorder.finalize()["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertEqual(step["error"], "RuntimeError: api down")
            self.assertIsNone(step["output"])

    def test_stream_midway_failure_records_error_and_partial_text(self) -> None:
        def broken_stream():
            delta = SimpleNamespace(content="he")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
            raise RuntimeError("connection dropped")

        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.chat.completions.create = lambda **kwargs: broken_stream()
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            stream = wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
            )
            with self.assertRaises(RuntimeError):
                list(stream)
            step = recorder.finalize()["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertEqual(step["error"], "RuntimeError: connection dropped")
            self.assertEqual(step["output"]["content"], "he")
            self.assertTrue(step["output"]["truncated"])

    def test_abandoned_stream_marks_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.chat.completions.create = lambda **kwargs: _fake_stream()
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            stream = wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
            )
            first = next(stream)
            self.assertEqual(first.choices[0].delta.content, "he")
            stream.close()
            step = recorder.finalize()["steps"][0]
            self.assertEqual(step["status"], "ok")
            self.assertTrue(step["output"]["truncated"])
            self.assertEqual(step["output"]["content"], "he")

    def test_api_key_in_messages_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "my key is sk-abcdefghijklmnop123456"}],
            )
            bundle = recorder.finalize()
            self.assertEqual(bundle["steps"][0]["input"]["messages"][0]["content"], "[REDACTED]")
            self.assertIn("/steps/0/input/messages/0/content", bundle["redactions"])


async def _fake_async_stream():
    for token in ("he", "llo"):
        delta = SimpleNamespace(content=token)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class AsyncOpenAIIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def _client(self, acreate) -> _FakeClient:
        client = _FakeClient()
        client.chat.completions.create = acreate
        return client

    async def test_async_create_records_model_step_with_cost(self) -> None:
        async def acreate(**kwargs):
            return _FakeResponse()

        recorder = RunRecorder(cwd=".", argv=["demo"])
        wrapped = wrap(self._client(acreate), recorder)
        response = await wrapped.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
        )
        self.assertEqual(response.model_dump()["choices"][0]["message"]["content"], "pong")
        step = recorder.finalize()["steps"][0]
        self.assertEqual(step["kind"], "model")
        self.assertEqual(step["cost"]["total_tokens"], 18)
        self.assertEqual(step["metadata"]["model"], "gpt-4o-mini")

    async def test_async_stream_records_full_text(self) -> None:
        async def acreate(**kwargs):
            return _fake_async_stream()

        recorder = RunRecorder(cwd=".", argv=["demo"])
        wrapped = wrap(self._client(acreate), recorder)
        stream = await wrapped.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            stream=True,
        )
        collected = [chunk.choices[0].delta.content async for chunk in stream]
        step = recorder.finalize()["steps"][0]
        self.assertEqual("".join(collected), "hello")
        self.assertEqual(step["output"]["content"], "hello")
        self.assertFalse(step["output"]["truncated"])

    async def test_async_abandoned_stream_marks_truncated(self) -> None:
        async def acreate(**kwargs):
            return _fake_async_stream()

        recorder = RunRecorder(cwd=".", argv=["demo"])
        wrapped = wrap(self._client(acreate), recorder)
        stream = await wrapped.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            stream=True,
        )
        first = await anext(stream)
        self.assertEqual(first.choices[0].delta.content, "he")
        await stream.aclose()
        step = recorder.finalize()["steps"][0]
        self.assertEqual(step["status"], "ok")
        self.assertTrue(step["output"]["truncated"])
        self.assertEqual(step["output"]["content"], "he")

    async def test_async_stream_midway_failure_records_error_and_partial_text(self) -> None:
        async def broken_stream():
            delta = SimpleNamespace(content="he")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
            raise RuntimeError("connection dropped")

        async def acreate(**kwargs):
            return broken_stream()

        recorder = RunRecorder(cwd=".", argv=["demo"])
        wrapped = wrap(self._client(acreate), recorder)
        stream = await wrapped.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            stream=True,
        )
        with self.assertRaises(RuntimeError):
            async for _ in stream:
                pass
        step = recorder.finalize()["steps"][0]
        self.assertEqual(step["status"], "error")
        self.assertEqual(step["error"], "RuntimeError: connection dropped")
        self.assertEqual(step["output"]["content"], "he")
        self.assertTrue(step["output"]["truncated"])

    async def test_async_stream_create_failure_records_error_step(self) -> None:
        async def acreate(**kwargs):
            raise RuntimeError("api down")

        recorder = RunRecorder(cwd=".", argv=["demo"])
        wrapped = wrap(self._client(acreate), recorder)
        with self.assertRaises(RuntimeError):
            await wrapped.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True)
        step = recorder.finalize()["steps"][0]
        self.assertEqual(step["status"], "error")
        self.assertEqual(step["error"], "RuntimeError: api down")


if __name__ == "__main__":
    unittest.main()
