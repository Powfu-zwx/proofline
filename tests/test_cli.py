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
    def test_run_records_output_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            child = "import sys; sys.stdout.buffer.write(b'hi\\n')"
            code, stdout, _ = _run_main(
                ["run", "--out", str(out), "--", sys.executable, "-c", child]
            )
            self.assertEqual(code, 0)
            self.assertIn("hi", stdout)
            self.assertEqual(verify_bundle(out), [])
            step = read_bundle(out)["steps"][0]
            self.assertEqual(step["kind"], "process")
            self.assertEqual(step["status"], "ok")
            self.assertEqual(step["output"]["returncode"], 0)
            self.assertEqual(step["output"]["stdout"]["text"], "hi\n")
            self.assertFalse(step["output"]["stdout"]["truncated"])
            self.assertEqual(step["output"]["stderr"]["length"], 0)

    def test_run_propagates_exit_code_and_records_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            child = "import sys; sys.stderr.buffer.write(b'boom'); sys.exit(3)"
            code, _, stderr = _run_main(
                ["run", "--out", str(out), "--", sys.executable, "-c", child]
            )
            self.assertEqual(code, 3)
            self.assertIn("boom", stderr)
            self.assertEqual(verify_bundle(out), [])
            step = read_bundle(out)["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertEqual(step["output"]["returncode"], 3)
            self.assertEqual(step["output"]["stderr"]["text"], "boom")

    def test_run_recording_and_echo_are_encoding_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            narrow_stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
            child = "import sys; sys.stdout.buffer.write('caf\\u00e9\\n'.encode('utf-8'))"
            with contextlib.redirect_stdout(narrow_stdout), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = main(["run", "--out", str(out), "--", sys.executable, "-c", child])
            self.assertEqual(code, 0)
            self.assertEqual(verify_bundle(out), [])
            step = read_bundle(out)["steps"][0]
            self.assertEqual(step["status"], "ok")
            self.assertEqual(step["output"]["stdout"]["text"], "caf\u00e9\n")

    def test_run_truncates_preview_but_digests_all_bytes(self) -> None:
        import hashlib

        from proofline.cli import OUTPUT_CAP

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            child = f"import sys; sys.stdout.buffer.write(b'x' * {OUTPUT_CAP * 2})"
            code, _, _ = _run_main(
                ["run", "--out", str(out), "--", sys.executable, "-c", child]
            )
            self.assertEqual(code, 0)
            self.assertEqual(verify_bundle(out), [])
            recorded = read_bundle(out)["steps"][0]["output"]["stdout"]
            full_bytes = b"x" * (OUTPUT_CAP * 2)
            self.assertTrue(recorded["truncated"])
            self.assertEqual(len(recorded["text"]), OUTPUT_CAP)
            self.assertEqual(recorded["length"], len(full_bytes))
            self.assertEqual(recorded["sha256"], hashlib.sha256(full_bytes).hexdigest())

    def test_run_without_command_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            code, _, stderr = _run_main(["run", "--out", str(out), "--"])
            self.assertEqual(code, 2)
            self.assertIn("no command given", stderr)
            self.assertFalse(out.exists())

    def test_run_nonexistent_command_still_writes_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "run.json"
            code, _, stderr = _run_main(
                ["run", "--out", str(out), "--", "proofline-no-such-command-xyz"]
            )
            self.assertEqual(code, 2)
            self.assertNotEqual(stderr, "")
            self.assertEqual(verify_bundle(out), [])
            step = read_bundle(out)["steps"][0]
            self.assertEqual(step["status"], "error")
            self.assertIn("FileNotFoundError", step["error"])


class CliVersionTest(unittest.TestCase):
    def test_version_flag_prints_version_and_exits_zero(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("proofline", stdout.getvalue())


class CliVerifyTest(unittest.TestCase):
    def test_verify_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = _record_bundle(directory, "run.json")
            code, stdout, _ = _run_main(["verify", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("OK", stdout)

    def test_verify_missing_file_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, _, stderr = _run_main(["verify", str(Path(directory) / "absent.json")])
            self.assertEqual(code, 2)
            self.assertNotEqual(stderr, "")

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


class CliSignTest(unittest.TestCase):
    def test_keygen_sign_and_verify_signed_by(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, stdout, _ = _run_main(["keygen", "--out", directory])
            self.assertEqual(code, 0)
            private_path = Path(directory) / "proofline-signing.pem"
            public_path = Path(directory) / "proofline-signing.pub.pem"
            self.assertTrue(private_path.exists())

            out = _record_bundle(directory, "run.json")
            code, stdout, _ = _run_main(["sign", str(out), "--key", str(private_path)])
            self.assertEqual(code, 0)
            self.assertIn("signed", stdout)

            code, _, _ = _run_main(["verify", str(out), "--signed-by", str(public_path)])
            self.assertEqual(code, 0)

    def test_verify_signed_by_rejects_wrong_key(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _run_main(["keygen", "--out", first])
            _run_main(["keygen", "--out", second])
            out = _record_bundle(first, "run.json")
            _run_main(["sign", str(out), "--key", str(Path(first) / "proofline-signing.pem")])
            code, _, stderr = _run_main(
                ["verify", str(out), "--signed-by", str(Path(second) / "proofline-signing.pub.pem")]
            )
            self.assertEqual(code, 1)
            self.assertIn("no valid signature", stderr)


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
