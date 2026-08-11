from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofline import Policy, PolicyViolation, RunRecorder


class PolicyTest(unittest.TestCase):
    def test_write_inside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = RunRecorder(
                cwd=directory,
                argv=["demo"],
                policy=Policy(allowed_write_roots=(root,)),
            )
            out = root / "run.json"
            recorder.finalize(out)
            self.assertTrue(out.exists())

    def test_write_outside_allowed_roots_raises(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as other:
            recorder = RunRecorder(
                cwd=allowed,
                argv=["demo"],
                policy=Policy(allowed_write_roots=(Path(allowed),)),
            )
            out = Path(other) / "run.json"
            with self.assertRaises(PolicyViolation):
                recorder.finalize(out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
