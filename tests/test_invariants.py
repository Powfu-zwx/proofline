"""Cross-module invariants that individual unit tests do not pin down."""

from __future__ import annotations

import tempfile
import unittest

from proofline import RunRecorder, verify_bundle
from proofline.model import canonical_json
from proofline.redact import redact


class InvariantTest(unittest.TestCase):
    def test_canonical_json_ignores_key_insertion_order(self) -> None:
        left = {"b": 1, "a": {"y": [1, {"k": 2}], "x": 3}}
        right = {"a": {"x": 3, "y": [1, {"k": 2}]}, "b": 1}
        self.assertEqual(canonical_json(left), canonical_json(right))

    def test_redaction_is_idempotent_on_values(self) -> None:
        value = {
            "api_key": "sk-abcdefghijklmnop123456",
            "nested": {"credentials": {"user": "u", "password": "p"}},
            "note": "Bearer abcdefghijklmnopqrstuvwxyz",
            "plain": [1, "two", None],
        }
        once, _ = redact(value)
        twice, _ = redact(once)
        self.assertEqual(once, twice)

    def test_recorded_redaction_pointers_resolve_through_verify(self) -> None:
        """redact escapes pointer parts; verify must unescape them identically."""
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            with recorder.step(
                "custom",
                "weird-keys",
                input={"a/b_token": "x", "c~d_secret": "y", "api_key": "z"},
            ) as step:
                step["output"] = {"ok": True}
            bundle = recorder.finalize()

            self.assertEqual(verify_bundle(bundle), [])
            self.assertIn("/steps/0/input/a~1b_token", bundle["redactions"])
            self.assertIn("/steps/0/input/c~0d_secret", bundle["redactions"])
            self.assertIn("/steps/0/input/api_key", bundle["redactions"])


if __name__ == "__main__":
    unittest.main()
