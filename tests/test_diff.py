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


def _step(name: str, output: dict, kind: str = "model") -> dict:
    return {
        "step_id": f"step-{name}",
        "kind": kind,
        "name": name,
        "status": "ok",
        "started_at": "2026-01-01T00:00:00.000Z",
        "ended_at": "2026-01-01T00:00:01.000Z",
        "input": {"q": name},
        "output": output,
        "error": None,
        "cost": None,
        "metadata": {},
    }


def _bundle(steps: list[dict]) -> dict:
    return {"schema_version": "0.1", "steps": steps}


class AlignedStepsDiffTest(unittest.TestCase):
    def test_inserted_step_does_not_cascade(self) -> None:
        left = _bundle([_step("a", {"v": 1}), _step("b", {"v": 2}), _step("c", {"v": 3})])
        right = _bundle(
            [
                _step("a", {"v": 1}),
                _step("b", {"v": 2}),
                _step("extra", {"v": 9}, kind="tool"),
                _step("c", {"v": 3}),
            ]
        )
        differences = diff_bundles(left, right)
        self.assertEqual(
            differences,
            ["$.steps: length 3 != 4", "$.steps[2]: added step (tool/extra)"],
        )

    def test_positional_step_ids_do_not_report_as_noise(self) -> None:
        def positional(step: dict, index: int) -> dict:
            return {**step, "step_id": f"step-{index + 1}"}

        left = _bundle(
            [
                positional(_step("a", {"v": 1}), 0),
                positional(_step("b", {"v": 2}), 1),
                positional(_step("c", {"v": 3}), 2),
            ]
        )
        right_steps = [
            positional(_step("a", {"v": 1}), 0),
            positional(_step("b", {"v": 2}), 1),
            positional(_step("extra", {"v": 9}, kind="tool"), 2),
            positional(_step("c", {"v": 3}), 3),
        ]
        right = _bundle(right_steps)
        self.assertEqual(
            diff_bundles(left, right),
            ["$.steps: length 3 != 4", "$.steps[2]: added step (tool/extra)"],
        )

    def test_changed_middle_step_reports_field_diff_only(self) -> None:
        left = _bundle([_step("a", {"v": 1}), _step("b", {"v": 2}), _step("c", {"v": 3})])
        right = _bundle([_step("a", {"v": 1}), _step("b", {"v": 99}), _step("c", {"v": 3})])
        self.assertEqual(diff_bundles(left, right), ["$.steps[1].output.v: 2 != 99"])

    def test_removed_step_reported_without_noise(self) -> None:
        left = _bundle([_step("a", {"v": 1}), _step("b", {"v": 2}), _step("c", {"v": 3})])
        right = _bundle([_step("a", {"v": 1}), _step("c", {"v": 3})])
        self.assertEqual(
            diff_bundles(left, right),
            ["$.steps: length 3 != 2", "$.steps[1]: removed step (model/b)"],
        )

    def test_renamed_step_pairs_as_removed_and_added(self) -> None:
        left = _bundle([_step("a", {"v": 1}), _step("b", {"v": 2})])
        right = _bundle([_step("a", {"v": 1}), _step("renamed", {"v": 2})])
        self.assertEqual(
            diff_bundles(left, right),
            [
                "$.steps[1]: removed step (model/b)",
                "$.steps[1]: added step (model/renamed)",
            ],
        )

    def test_repeated_step_names_still_pair_positionally(self) -> None:
        left = _bundle([_step("call", {"v": 1}), _step("call", {"v": 2})])
        right = _bundle([_step("call", {"v": 1}), _step("call", {"v": 20})])
        self.assertEqual(diff_bundles(left, right), ["$.steps[1].output.v: 2 != 20"])

    def test_reordered_steps_report_as_removed_and_added(self) -> None:
        left = _bundle([_step("a", {"v": 1}), _step("b", {"v": 2})])
        right = _bundle([_step("b", {"v": 2}), _step("a", {"v": 1})])
        differences = diff_bundles(left, right)
        self.assertEqual(len(differences), 2)
        self.assertIn("$.steps[1]: removed step (model/b)", differences)
        self.assertIn("$.steps[0]: added step (model/b)", differences)


if __name__ == "__main__":
    unittest.main()
