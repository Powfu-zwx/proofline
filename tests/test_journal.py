from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from proofline import Policy, PolicyViolation, RunRecorder, verify_bundle
from proofline.diff import diff_bundles
from proofline.journal import (
    JournalError,
    bundle_from_journal,
    default_bundle_path,
    read_journal,
    recover,
)
from proofline.model import stable_digest


def _steps(recorder: RunRecorder) -> None:
    with recorder.step(
        "model", "draft", input={"prompt": "hi", "api_key": "sk-abcdefghijklmnop123456"}
    ) as step:
        step["output"] = {"text": "ok"}
        step["cost"] = {"input_tokens": 3, "output_tokens": 1}
    with recorder.step("tool", "run", input={"cmd": "ls"}) as step:
        step["output"] = {"lines": ["a", "b"]}


class JournalParityTest(unittest.TestCase):
    def test_journal_bundle_matches_memory_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory = RunRecorder(
                cwd=directory, argv=["python", "demo.py"], metadata={"note": "x"}
            )
            _steps(memory)
            memory_bundle = memory.finalize()

            out = Path(directory) / "run.json"
            journaled = RunRecorder(
                cwd=directory,
                argv=["python", "demo.py"],
                metadata={"note": "x"},
                out_path=out,
                journal=True,
            )
            _steps(journaled)
            journal_bundle = journaled.finalize()

            self.assertEqual(stable_digest(journal_bundle), stable_digest(memory_bundle))
            self.assertEqual(diff_bundles(memory_bundle, journal_bundle), [])
            self.assertEqual(verify_bundle(out), [])
            self.assertFalse(Path(f"{out}.journal").exists())

    def test_journal_mode_does_not_accumulate_steps_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            recorder = RunRecorder(cwd=directory, argv=["demo"], out_path=out, journal=True)
            _steps(recorder)
            self.assertEqual(recorder.steps, [])
            self.assertEqual(recorder._step_count, 2)
            recorder.finalize()
            self.assertTrue(out.exists())


class CrashRecoveryTest(unittest.TestCase):
    def test_crashed_run_recovers_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["python", "demo.py"], journal=journal)
            _steps(recorder)
            recorder._journal.close()  # crash: no finalize, evidence only in the journal

            bundle = recover(journal)
            self.assertEqual(len(bundle["steps"]), 2)
            self.assertEqual(bundle["steps"][1]["output"], {"lines": ["a", "b"]})
            self.assertEqual(verify_bundle(bundle), [])
            self.assertFalse(journal.exists())
            self.assertTrue((Path(directory) / "run.json").exists())

    def test_error_step_is_journaled_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            with self.assertRaises(RuntimeError):
                with recorder.step("model", "boom", input={"prompt": "hi"}):
                    raise RuntimeError("bang")
            recorder._journal.close()

            bundle = bundle_from_journal(journal)
            self.assertEqual(bundle["steps"][0]["status"], "error")
            self.assertIn("RuntimeError", bundle["steps"][0]["error"])
            self.assertEqual(verify_bundle(bundle), [])

    def test_torn_tail_line_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            _steps(recorder)
            recorder._journal.close()
            with journal.open("ab") as handle:
                handle.write(b'{"t": "ste')  # crash mid-append

            _, records = read_journal(journal)
            self.assertEqual(len(records), 2)
            self.assertEqual(verify_bundle(recover(journal)), [])

    def test_corrupt_interior_line_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            with recorder.step("custom", "one", input={"x": 1}) as step:
                step["output"] = {"y": 2}
            recorder._journal.close()
            lines = journal.read_text(encoding="utf-8").splitlines()
            lines.insert(1, "not-json-at-all{")
            journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(JournalError, "line 2 is corrupt"):
                read_journal(journal)

    def test_non_journal_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "stray.journal"
            journal.write_text(json.dumps({"unrelated": True}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(JournalError, "not a proofline journal"):
                read_journal(journal)

    def test_future_journal_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            recorder._journal.close()
            header, step_records = read_journal(journal)
            lines = [json.dumps({**header, "v": 99})] + [
                json.dumps(record) for record in step_records
            ]
            journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(JournalError, "unsupported journal version"):
                read_journal(journal)


class JournalGuardTest(unittest.TestCase):
    def test_journal_true_requires_out_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires out_path"):
            RunRecorder(cwd=".", argv=["demo"], journal=True)

    def test_policy_blocks_journal_path_at_init(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as other:
            with self.assertRaises(PolicyViolation):
                RunRecorder(
                    cwd=allowed,
                    argv=["demo"],
                    policy=Policy(allowed_write_roots=(Path(allowed),)),
                    journal=Path(other) / "run.json.journal",
                )
            self.assertFalse((Path(other) / "run.json.journal").exists())

    def test_step_after_finalize_raises_in_journal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            recorder = RunRecorder(cwd=directory, argv=["demo"], out_path=out, journal=True)
            recorder.finalize()
            with self.assertRaisesRegex(RuntimeError, "journal is closed"):
                with recorder.step("custom", "late", input={"x": 1}):
                    pass

    def test_finalize_without_target_keeps_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "evidence.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            _steps(recorder)
            bundle = recorder.finalize()
            self.assertEqual(verify_bundle(bundle), [])
            self.assertTrue(journal.exists())
            self.assertEqual(default_bundle_path(journal), Path(directory) / "evidence")


class JournalCliTest(unittest.TestCase):
    def _run_main(self, argv: list[str]) -> tuple[int, str, str]:
        from proofline.cli import main

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_recover_writes_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            _steps(recorder)
            recorder._journal.close()

            out = Path(directory) / "recovered.json"
            code, stdout, _ = self._run_main(["recover", str(journal), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("recovered 2 steps", stdout)
            self.assertEqual(verify_bundle(out), [])
            self.assertFalse(journal.exists())

    def test_recover_defaults_output_next_to_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            recorder = RunRecorder(cwd=directory, argv=["demo"], journal=journal)
            _steps(recorder)
            recorder._journal.close()

            code, _, _ = self._run_main(["recover", str(journal)])
            self.assertEqual(code, 0)
            self.assertEqual(verify_bundle(Path(directory) / "run.json"), [])

    def test_recover_corrupt_journal_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "run.json.journal"
            journal.write_text("garbage\n", encoding="utf-8")
            code, _, stderr = self._run_main(["recover", str(journal)])
            self.assertEqual(code, 2)
            self.assertIn("journal", stderr)


if __name__ == "__main__":
    unittest.main()
