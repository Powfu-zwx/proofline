from __future__ import annotations

import tempfile
import unittest
from typing import Any

from proofline import RunRecorder, verify_bundle
from proofline.model import stable_digest


def _bundle() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        recorder = RunRecorder(cwd=directory, argv=["python", "demo.py"])
        with recorder.step("custom", "same", input={"x": 1}) as step:
            step["output"] = {"y": 2}
        return recorder.finalize()


def _reseal(bundle: dict[str, Any]) -> dict[str, Any]:
    bundle["bundle_digest"] = stable_digest(bundle)
    return bundle


class VerifyNegativeTest(unittest.TestCase):
    def test_valid_bundle_passes(self) -> None:
        self.assertEqual(verify_bundle(_bundle()), [])

    def test_non_object_rejected(self) -> None:
        self.assertEqual(verify_bundle([]), ["bundle must be a JSON object"])

    def test_tampered_output_reports_both_digests(self) -> None:
        bundle = _bundle()
        bundle["steps"][0]["output"] = {"y": 999}
        errors = verify_bundle(bundle)
        self.assertIn("steps[0].output_digest mismatch", errors)
        self.assertIn("bundle_digest mismatch", errors)

    def test_missing_top_level_field(self) -> None:
        bundle = _bundle()
        del bundle["actor"]
        errors = verify_bundle(_reseal(bundle))
        self.assertIn("missing top-level fields: actor", errors)

    def test_unsupported_schema_version(self) -> None:
        bundle = _bundle()
        bundle["schema_version"] = "9.9"
        errors = verify_bundle(_reseal(bundle))
        self.assertEqual(errors, ["unsupported schema_version: '9.9'"])

    def test_invalid_step_kind_and_status(self) -> None:
        bundle = _bundle()
        bundle["steps"][0]["kind"] = "llm"
        bundle["steps"][0]["status"] = "done"
        errors = verify_bundle(_reseal(bundle))
        self.assertIn("steps[0].kind is invalid: 'llm'", errors)
        self.assertIn("steps[0].status is invalid: 'done'", errors)

    def test_unredacted_secret_value_flagged(self) -> None:
        bundle = _bundle()
        bundle["metadata"]["note"] = "sk-abcdefghijklmnop123456"
        errors = verify_bundle(_reseal(bundle))
        self.assertTrue(any("/metadata/note" in error for error in errors))

    def test_unredacted_secret_key_flagged(self) -> None:
        bundle = _bundle()
        bundle["metadata"]["credentials"] = "hunter2"
        errors = verify_bundle(_reseal(bundle))
        self.assertTrue(any("/metadata/credentials" in error for error in errors))

    def test_unresolvable_redaction_path(self) -> None:
        bundle = _bundle()
        bundle["redactions"] = ["/steps/9/input"]
        errors = verify_bundle(_reseal(bundle))
        self.assertEqual(errors, ["redaction path does not resolve: /steps/9/input"])

    def test_array_index_with_leading_zero_does_not_resolve(self) -> None:
        """RFC 6901 forbids leading zeros in array indices."""
        bundle = _bundle()
        bundle["redactions"] = ["/steps/00"]
        errors = verify_bundle(_reseal(bundle))
        self.assertEqual(errors, ["redaction path does not resolve: /steps/00"])

    def test_redactions_must_be_string_array(self) -> None:
        bundle = _bundle()
        bundle["redactions"] = "nope"
        errors = verify_bundle(_reseal(bundle))
        self.assertEqual(errors, ["redactions must be an array of JSON Pointer strings"])


if __name__ == "__main__":
    unittest.main()
