from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofline import RunRecorder, verify_bundle
from proofline.model import stable_digest


class RunRecorderTest(unittest.TestCase):
    def test_records_redacts_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            recorder = RunRecorder(
                cwd=directory,
                argv=["python", "demo.py"],
                metadata={"api_key": "secret"},
                out_path=out,
            )
            with recorder.step(
                "model",
                "draft",
                input={"prompt": "hi", "authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456"},
            ) as step:
                step["output"] = {"text": "ok", "tokens": 3}
            bundle = recorder.finalize()

            self.assertEqual(bundle["metadata"]["api_key"], "[REDACTED]")
            self.assertEqual(bundle["steps"][0]["input"]["authorization"], "[REDACTED]")
            self.assertIn("/metadata/api_key", bundle["redactions"])
            self.assertIn("/steps/0/input/authorization", bundle["redactions"])
            self.assertTrue(out.exists())
            self.assertEqual(verify_bundle(out), [])

    def test_redact_handles_nested_secret_containers(self) -> None:
        recorder = RunRecorder(
            cwd=".",
            argv=["demo"],
            metadata={"nested": {"api_key": {"value": "x"}, "list": ["token_abc"]}},
        )
        self.assertEqual(recorder.metadata["nested"]["api_key"], "[REDACTED]")
        self.assertEqual(recorder.metadata["nested"]["list"], ["token_abc"])

    def test_invalid_step_kind_fails_fast(self) -> None:
        recorder = RunRecorder(cwd=".", argv=["demo"])
        with self.assertRaises(ValueError):
            with recorder.step("llm", "draft"):
                pass
        self.assertEqual(recorder.steps, [])

    def test_unserializable_input_fails_fast(self) -> None:
        recorder = RunRecorder(cwd=".", argv=["demo"])
        with self.assertRaisesRegex(TypeError, "JSON-serializable"):
            with recorder.step("custom", "draft", input={"payload": object()}):
                pass
        self.assertEqual(recorder.steps, [])

    def test_stable_digest_ignores_volatile_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def record() -> dict:
                recorder = RunRecorder(cwd=directory, argv=["python", "demo.py"])
                with recorder.step("custom", "same", input={"x": 1}) as step:
                    step["output"] = {"y": 2}
                return recorder.finalize()

            self.assertEqual(stable_digest(record()), stable_digest(record()))


if __name__ == "__main__":
    unittest.main()
