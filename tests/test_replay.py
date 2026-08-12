from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from proofline import RunRecorder
from proofline.diff import diff_bundles
from proofline.model import sha256_json, stable_digest
from proofline.openai import wrap
from proofline.replay import REPLAY_ENV, ReplayedView, ReplayMismatch, ReplaySource


class _FakeResponse:
    def __init__(self) -> None:
        self.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }


class _PoisonedCompletions:
    def create(self, **kwargs):
        raise AssertionError("the provider must not be called during replay")


def _live_client():
    completions = SimpleNamespace(create=lambda **kwargs: _FakeResponse())
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _poisoned_client():
    return SimpleNamespace(chat=SimpleNamespace(completions=_PoisonedCompletions()))


def _fake_stream():
    for token in ("he", "llo"):
        delta = SimpleNamespace(content=token)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


MESSAGES = [{"role": "user", "content": "ping"}]


def _record_baseline(directory: str, *, stream: bool = False) -> dict:
    client = _live_client()
    if stream:
        client.chat.completions.create = lambda **kwargs: _fake_stream()
    recorder = RunRecorder(cwd=directory, argv=["demo"])
    wrapped = wrap(client, recorder)
    if stream:
        list(wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES, stream=True))
    else:
        wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
    return recorder.finalize()


class StrictReplayTest(unittest.TestCase):
    def test_serves_recorded_response_without_calling_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory)
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            response = wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
            self.assertEqual(response.choices[0].message.content, "pong")
            self.assertEqual(response.usage.total_tokens, 18)

    def test_replayed_run_diffs_empty_against_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory)
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
            replayed = recorder.finalize()
            self.assertEqual(diff_bundles(baseline, replayed), [])
            self.assertEqual(baseline["bundle_digest"], replayed["bundle_digest"])

    def test_mismatch_reports_pointer_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory)
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            with self.assertRaises(ReplayMismatch) as ctx:
                wrapped.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "changed"}],
                )
            self.assertIn("messages[0].content", str(ctx.exception))

    def test_each_recorded_step_is_served_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory)
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
            with self.assertRaisesRegex(ReplayMismatch, "remaining"):
                wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)

    def test_secret_bearing_request_matches_redacted_baseline(self) -> None:
        secret_messages = [{"role": "user", "content": "key is sk-abcdefghijklmnop123456"}]
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_live_client(), recorder)
            wrapped.chat.completions.create(model="gpt-4o-mini", messages=secret_messages)
            baseline = recorder.finalize()

            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            response = wrapped.chat.completions.create(
                model="gpt-4o-mini", messages=secret_messages
            )
            self.assertEqual(response.choices[0].message.content, "pong")


class OrderedReplayTest(unittest.TestCase):
    def test_changed_input_still_completes_for_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory)
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            source = ReplaySource(baseline, strategy="ordered")
            wrapped = wrap(_poisoned_client(), recorder, replay=source)
            response = wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "changed prompt"}],
            )
            self.assertEqual(response.choices[0].message.content, "pong")
            differences = diff_bundles(baseline, recorder.finalize())
            self.assertTrue(any("input.messages[0].content" in d for d in differences))
            self.assertFalse(any(".output." in d for d in differences))

    def test_stream_mode_mismatch_is_rejected_at_call_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory)
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            source = ReplaySource(baseline, strategy="ordered")
            wrapped = wrap(_poisoned_client(), recorder, replay=source)
            with self.assertRaisesRegex(ReplayMismatch, "not streamed"):
                wrapped.chat.completions.create(
                    model="gpt-4o-mini", messages=MESSAGES, stream=True
                )
            step = recorder.finalize()["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertIn("ReplayMismatch", step["error"])


class StreamReplayTest(unittest.TestCase):
    def test_stream_replays_chunk_by_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory, stream=True)
            recorded_output = baseline["steps"][0]["output"]
            self.assertEqual(recorded_output["chunks"], ["he", "llo"])

            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            stream = wrapped.chat.completions.create(
                model="gpt-4o-mini", messages=MESSAGES, stream=True
            )
            collected = [chunk.choices[0].delta.content for chunk in stream]
            self.assertEqual(collected, ["he", "llo"])
            self.assertEqual(diff_bundles(baseline, recorder.finalize()), [])

    def test_legacy_bundle_without_chunks_replays_single_piece(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = _record_baseline(directory, stream=True)
            output = baseline["steps"][0]["output"]
            del output["chunks"]
            baseline["steps"][0]["output_digest"] = sha256_json(output)
            baseline["bundle_digest"] = stable_digest(baseline)

            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_poisoned_client(), recorder, replay=ReplaySource(baseline))
            stream = wrapped.chat.completions.create(
                model="gpt-4o-mini", messages=MESSAGES, stream=True
            )
            collected = [chunk.choices[0].delta.content for chunk in stream]
            self.assertEqual(collected, ["hello"])


class ReplayGuardsTest(unittest.TestCase):
    def test_error_step_cannot_be_replayed(self) -> None:
        def boom(**kwargs):
            raise RuntimeError("api down")

        with tempfile.TemporaryDirectory() as directory:
            client = _live_client()
            client.chat.completions.create = boom
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder)
            with self.assertRaises(RuntimeError):
                wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
            baseline = recorder.finalize()

            recorder = RunRecorder(cwd=directory, argv=["demo"])
            source = ReplaySource(baseline, strategy="ordered")
            wrapped = wrap(_poisoned_client(), recorder, replay=source)
            with self.assertRaisesRegex(ReplayMismatch, "no output"):
                wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)

    def test_unknown_strategy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReplaySource({"steps": []}, strategy="fuzzy")

    def test_env_var_activates_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(_live_client(), recorder)
            wrapped.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)
            baseline_path = Path(directory) / "baseline.run.json"
            recorder.finalize(baseline_path)

            with mock.patch.dict("os.environ", {REPLAY_ENV: str(baseline_path)}):
                recorder = RunRecorder(cwd=directory, argv=["demo"])
                wrapped = wrap(_poisoned_client(), recorder)
                response = wrapped.chat.completions.create(
                    model="gpt-4o-mini", messages=MESSAGES
                )
            self.assertEqual(response.choices[0].message.content, "pong")


class ReplayedViewTest(unittest.TestCase):
    def test_attribute_item_and_dump_access(self) -> None:
        data = {"choices": [{"message": {"content": "hi"}}], "usage": {"total_tokens": 3}}
        viewed = ReplayedView(data)
        self.assertEqual(viewed.choices[0].message.content, "hi")
        self.assertEqual(viewed["usage"]["total_tokens"], 3)
        dumped = viewed.model_dump()
        self.assertEqual(dumped, data)
        dumped["usage"]["total_tokens"] = 99
        self.assertEqual(viewed.usage.total_tokens, 3)

    def test_missing_attribute_raises_attribute_error(self) -> None:
        viewed = ReplayedView({"present": 1})
        self.assertIsNone(getattr(viewed, "absent", None))
        with self.assertRaises(AttributeError):
            _ = viewed.absent


class AsyncReplayTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_replay_serves_non_stream_and_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline_plain = _record_baseline(directory)
            baseline_stream = _record_baseline(directory, stream=True)

            async def poisoned(**kwargs):
                raise AssertionError("the provider must not be called during replay")

            client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=poisoned))
            )
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder, replay=ReplaySource(baseline_plain))
            response = await wrapped.chat.completions.create(
                model="gpt-4o-mini", messages=MESSAGES
            )
            self.assertEqual(response.choices[0].message.content, "pong")

            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap(client, recorder, replay=ReplaySource(baseline_stream))
            stream = await wrapped.chat.completions.create(
                model="gpt-4o-mini", messages=MESSAGES, stream=True
            )
            collected = [chunk.choices[0].delta.content async for chunk in stream]
            self.assertEqual(collected, ["he", "llo"])
            step = recorder.finalize()["steps"][0]
            self.assertEqual(step["output"]["content"], "hello")
            self.assertFalse(step["output"]["truncated"])


class AnthropicReplayTest(unittest.TestCase):
    def test_anthropic_replay_round_trip(self) -> None:
        from proofline.anthropic import wrap as wrap_anthropic

        class _AnthropicResponse:
            def __init__(self) -> None:
                self.usage = SimpleNamespace(input_tokens=9, output_tokens=4)

            def model_dump(self, mode: str = "json") -> dict:
                return {
                    "content": [{"type": "text", "text": "pong"}],
                    "usage": {"input_tokens": 9, "output_tokens": 4},
                }

        with tempfile.TemporaryDirectory() as directory:
            client = SimpleNamespace(
                messages=SimpleNamespace(create=lambda **kwargs: _AnthropicResponse())
            )
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap_anthropic(client, recorder)
            wrapped.messages.create(model="claude-sonnet-4-5", max_tokens=256, messages=MESSAGES)
            baseline = recorder.finalize()

            def poisoned(**kwargs):
                raise AssertionError("the provider must not be called during replay")

            client = SimpleNamespace(messages=SimpleNamespace(create=poisoned))
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            wrapped = wrap_anthropic(client, recorder, replay=ReplaySource(baseline))
            response = wrapped.messages.create(
                model="claude-sonnet-4-5", max_tokens=256, messages=MESSAGES
            )
            self.assertEqual(response.content[0].text, "pong")
            self.assertEqual(diff_bundles(baseline, recorder.finalize()), [])


if __name__ == "__main__":
    unittest.main()
