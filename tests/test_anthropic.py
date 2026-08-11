from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from proofline import RunRecorder, verify_bundle
from proofline.anthropic import wrap


class _FakeResponse:
    def __init__(self) -> None:
        self.usage = SimpleNamespace(input_tokens=9, output_tokens=4)

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "content": [{"type": "text", "text": "pong"}],
            "usage": {"input_tokens": 9, "output_tokens": 4},
        }


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _fake_stream():
    yield SimpleNamespace(type="message_start", delta=None)
    for token in ("he", "llo"):
        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text=token))
    yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(partial_json="{"))


class AnthropicIntegrationTest(unittest.TestCase):
    def test_create_records_model_step_with_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            client = _FakeClient()
            recorder = RunRecorder(cwd=directory, argv=["demo"], out_path=out)
            wrapped = wrap(client, recorder)
            response = wrapped.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": "ping"}],
            )
            self.assertEqual(response.model_dump()["content"][0]["text"], "pong")

            bundle = recorder.finalize()
            step = bundle["steps"][0]
            self.assertEqual(step["kind"], "model")
            self.assertEqual(step["name"], "messages.create")
            self.assertEqual(step["input"]["model"], "claude-sonnet-4-5")
            self.assertEqual(step["input"]["max_tokens"], 256)
            self.assertEqual(step["output"]["content"][0]["text"], "pong")
            self.assertEqual(
                step["cost"],
                {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
            )
            self.assertEqual(step["metadata"]["model"], "claude-sonnet-4-5")
            self.assertEqual(verify_bundle(out), [])

    def test_stream_records_text_deltas_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.messages.create = lambda **kwargs: _fake_stream()
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            stream = wrapped.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": "ping"}],
                stream=True,
            )
            events = list(stream)
            step = recorder.finalize()["steps"][0]
            self.assertEqual(len(events), 4)
            self.assertEqual(step["status"], "ok")
            self.assertEqual(step["output"]["content"], "hello")
            self.assertFalse(step["output"]["truncated"])

    def test_stream_create_failure_records_error_step(self) -> None:
        def boom(**kwargs):
            raise RuntimeError("api down")

        with tempfile.TemporaryDirectory() as directory:
            client = _FakeClient()
            client.messages.create = boom
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            with self.assertRaises(RuntimeError):
                wrapped.messages.create(model="claude-sonnet-4-5", messages=[], stream=True)
            step = recorder.finalize()["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertEqual(step["error"], "RuntimeError: api down")


if __name__ == "__main__":
    unittest.main()
