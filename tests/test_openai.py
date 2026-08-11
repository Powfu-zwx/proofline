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


class OpenAIIntegrationTest(unittest.TestCase):
    def test_create_records_model_step_with_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            client = _FakeClient()
            with RunRecorder(cwd=directory, argv=["demo"], out_path=out) as recorder:
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
        def fake_stream():
            for token in ("he", "llo"):
                delta = SimpleNamespace(content=token)
                yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.chat.completions.create = lambda **kwargs: fake_stream()
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            stream = wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
            )
            collected = [getattr(c.choices[0].delta, "content", "") for c in stream]
            bundle = recorder.finalize()
            step = bundle["steps"][0]
            self.assertEqual("".join(collected), "hello")
            self.assertEqual(step["output"]["content"], "hello")
            self.assertTrue(step["output"]["streamed"])

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


if __name__ == "__main__":
    unittest.main()
