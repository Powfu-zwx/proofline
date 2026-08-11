from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from proofline import RunRecorder, VerificationError
from proofline.testing import UPDATE_ENV, assert_matches_baseline


def _record(directory: str, output_value: int) -> dict:
    recorder = RunRecorder(cwd=directory, argv=["pytest"])
    with recorder.step("custom", "same", input={"x": 1}) as step:
        step["output"] = {"y": output_value}
    return recorder.finalize()


class BaselineAssertionTest(unittest.TestCase):
    def test_update_env_records_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.run.json"
            with mock.patch.dict("os.environ", {UPDATE_ENV: "1"}):
                assert_matches_baseline(_record(directory, 2), baseline)
            self.assertTrue(baseline.exists())

    def test_matching_run_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.run.json"
            with mock.patch.dict("os.environ", {UPDATE_ENV: "1"}):
                assert_matches_baseline(_record(directory, 2), baseline)
            assert_matches_baseline(_record(directory, 2), baseline)

    def test_diverging_run_fails_with_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.run.json"
            with mock.patch.dict("os.environ", {UPDATE_ENV: "1"}):
                assert_matches_baseline(_record(directory, 2), baseline)
            with self.assertRaises(AssertionError) as ctx:
                assert_matches_baseline(_record(directory, 3), baseline)
            self.assertIn("$.steps[0].output.y", str(ctx.exception))

    def test_missing_baseline_hints_update_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "missing.run.json"
            with self.assertRaises(AssertionError) as ctx:
                assert_matches_baseline(_record(directory, 2), baseline)
            self.assertIn(UPDATE_ENV, str(ctx.exception))

    def test_tampered_candidate_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.run.json"
            bundle = _record(directory, 2)
            with mock.patch.dict("os.environ", {UPDATE_ENV: "1"}):
                assert_matches_baseline(bundle, baseline)
            tampered = _record(directory, 2)
            tampered["steps"][0]["output"] = {"y": 999}
            with self.assertRaises(VerificationError):
                assert_matches_baseline(tampered, baseline)


if __name__ == "__main__":
    unittest.main()
