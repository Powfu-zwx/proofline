from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofline import RunRecorder
from proofline.diff import diff_bundles


class DiffTest(unittest.TestCase):
    def test_semantic_diff_ignores_run_id_and_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.json"
            right = Path(directory) / "right.json"

            with RunRecorder(cwd=directory, argv=["python", "demo.py"], out_path=left) as recorder:
                with recorder.step("custom", "same", input={"x": 1}) as step:
                    step["output"] = {"y": 2}
            with RunRecorder(cwd=directory, argv=["python", "demo.py"], out_path=right) as recorder:
                with recorder.step("custom", "same", input={"x": 1}) as step:
                    step["output"] = {"y": 2}

            self.assertEqual(diff_bundles(left, right), [])

    def test_semantic_diff_finds_output_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.json"
            right = Path(directory) / "right.json"

            with RunRecorder(cwd=directory, argv=["python", "demo.py"], out_path=left) as recorder:
                with recorder.step("custom", "same", input={"x": 1}) as step:
                    step["output"] = {"y": 2}
            with RunRecorder(cwd=directory, argv=["python", "demo.py"], out_path=right) as recorder:
                with recorder.step("custom", "same", input={"x": 1}) as step:
                    step["output"] = {"y": 3}

            differences = diff_bundles(left, right)
            self.assertTrue(any("$.steps[0].output.y" in item for item in differences))

    def test_semantic_diff_reports_type_key_and_length_changes(self) -> None:
        left = {"a": 1, "only_left": True, "items": [1, 2], "steps": []}
        right = {"a": "1", "only_right": True, "items": [1], "steps": []}
        differences = diff_bundles(left, right)
        self.assertIn("$.a: type int != str", differences)
        self.assertIn("$.only_left: missing in right", differences)
        self.assertIn("$.only_right: missing in left", differences)
        self.assertIn("$.items: length 2 != 1", differences)


if __name__ == "__main__":
    unittest.main()
