from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from proofline import RunRecorder, verify_bundle
from proofline.cli import main
from proofline.storage import read_bundle, write_bundle


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _record_bundle(directory: str, name: str) -> Path:
    out = Path(directory) / name
    recorder = RunRecorder(cwd=directory, argv=["python", "demo.py"])
    with recorder.step("custom", "same", input={"x": 1}) as step:
        step["output"] = {"y": 2}
    recorder.finalize(out)
    return out


class CliRunTest(unittest.TestCase):
    def test_run_records_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            code, _, _ = _run_main(
                ["run", "--out", str(out), "--", sys.executable, "-c", "pass"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(verify_bundle(out), [])
            step = read_bundle(out)["steps"][0]
            self.assertEqual(step["kind"], "process")
            self.assertEqual(step["status"], "ok")
            self.assertEqual(step["output"], {"returncode": 0})

    def test_run_propagates_exit_code_and_records_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            code, _, _ = _run_main(
                ["run", "--out", str(out), "--", sys.executable, "-c", "raise SystemExit(3)"]
            )
            self.assertEqual(code, 3)
            self.assertEqual(verify_bundle(out), [])
            step = read_bundle(out)["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertEqual(step["output"], {"returncode": 3})

    def test_run_without_command_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            code, _, stderr = _run_main(["run", "--out", str(out), "--"])
            self.assertEqual(code, 2)
            self.assertIn("no command given", stderr)
            self.assertFalse(out.exists())


class CliVerifyTest(unittest.TestCase):
    def test_verify_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = _record_bundle(directory, "run.json")
            code, stdout, _ = _run_main(["verify", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("OK", stdout)

    def test_verify_tampered_bundle_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = _record_bundle(directory, "run.json")
            bundle = read_bundle(out)
            bundle["steps"][0]["output"] = {"y": 999}
            write_bundle(out, bundle)
            code, _, stderr = _run_main(["verify", str(out)])
            self.assertEqual(code, 1)
            self.assertIn("output_digest mismatch", stderr)
            self.assertIn("bundle_digest mismatch", stderr)


class CliDiffTest(unittest.TestCase):
    def test_diff_identical_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = _record_bundle(directory, "run.json")
            code, stdout, _ = _run_main(["diff", str(out), str(out)])
            self.assertEqual(code, 0)
            self.assertIn("no semantic differences", stdout)

    def test_diff_reports_semantic_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left = _record_bundle(directory, "left.json")
            right = Path(directory) / "right.json"
            bundle = read_bundle(left)
            bundle["steps"][0]["output"] = {"y": 3}
            write_bundle(right, bundle)
            code, stdout, _ = _run_main(["diff", str(left), str(right)])
            self.assertEqual(code, 1)
            self.assertIn("$.steps[0].output.y", stdout)


if __name__ == "__main__":
    unittest.main()
