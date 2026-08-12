from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from proofline import RunRecorder, verify_bundle
from proofline.diff import diff_bundles
from proofline.model import stable_digest
from proofline.sign import (
    MISSING_CRYPTO_HINT,
    generate_keypair,
    sign_bundle,
    signed_by,
    verify_signatures,
)


def _bundle(directory: str) -> dict:
    recorder = RunRecorder(cwd=directory, argv=["demo"])
    with recorder.step("custom", "same", input={"x": 1}) as step:
        step["output"] = {"y": 2}
    return recorder.finalize()


class SignTest(unittest.TestCase):
    def test_sign_and_verify_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path, public_path = generate_keypair(directory)
            self.assertTrue(private_path.exists())
            self.assertTrue(public_path.exists())

            bundle = sign_bundle(_bundle(directory), private_path)
            self.assertEqual(len(bundle["signatures"]), 1)
            self.assertEqual(bundle["signatures"][0]["algorithm"], "ed25519")
            self.assertEqual(verify_bundle(bundle), [])
            self.assertTrue(signed_by(bundle, public_path))

    def test_reseal_attack_is_caught(self) -> None:
        """Editing content and recomputing the digest must invalidate the signature."""
        with tempfile.TemporaryDirectory() as directory:
            private_path, _ = generate_keypair(directory)
            bundle = sign_bundle(_bundle(directory), private_path)

            bundle["steps"][0]["output"] = {"y": 999}
            bundle["steps"][0]["output_digest"] = None
            from proofline.model import sha256_json

            bundle["steps"][0]["output_digest"] = sha256_json({"y": 999})
            bundle["bundle_digest"] = stable_digest(bundle)
            errors = verify_bundle(bundle)
            self.assertTrue(any("does not verify" in error for error in errors))

    def test_volatile_field_tampering_is_caught(self) -> None:
        """The signature covers fields the stable digest deliberately ignores."""
        with tempfile.TemporaryDirectory() as directory:
            private_path, _ = generate_keypair(directory)
            bundle = sign_bundle(_bundle(directory), private_path)

            bundle["created_at"] = "1999-01-01T00:00:00.000Z"
            self.assertEqual(bundle["bundle_digest"], stable_digest(bundle))
            errors = verify_bundle(bundle)
            self.assertTrue(any("does not verify" in error for error in errors))

    def test_signatures_do_not_change_stable_digest_or_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path, _ = generate_keypair(directory)
            unsigned = _bundle(directory)
            digest_before = unsigned["bundle_digest"]
            signed = sign_bundle(dict(unsigned), private_path)
            self.assertEqual(stable_digest(signed), digest_before)
            self.assertEqual(diff_bundles(unsigned, signed), [])

    def test_multiple_signatures_all_verify(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            key_one, pub_one = generate_keypair(first)
            key_two, pub_two = generate_keypair(second)
            bundle = sign_bundle(_bundle(first), key_one)
            bundle = sign_bundle(bundle, key_two)
            self.assertEqual(len(bundle["signatures"]), 2)
            self.assertEqual(verify_signatures(bundle), [])
            self.assertTrue(signed_by(bundle, pub_one))
            self.assertTrue(signed_by(bundle, pub_two))

    def test_wrong_key_is_not_signed_by(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            key_one, _ = generate_keypair(first)
            _, pub_two = generate_keypair(second)
            bundle = sign_bundle(_bundle(first), key_one)
            self.assertFalse(signed_by(bundle, pub_two))

    def test_unsupported_algorithm_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path, _ = generate_keypair(directory)
            bundle = sign_bundle(_bundle(directory), private_path)
            bundle["signatures"][0]["algorithm"] = "rsa"
            errors = verify_signatures(bundle)
            self.assertTrue(any("unsupported" in error for error in errors))

    def test_corrupted_signature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path, _ = generate_keypair(directory)
            bundle = sign_bundle(_bundle(directory), private_path)
            bundle["signatures"][0]["signature"] = "AAAA" + bundle["signatures"][0]["signature"][4:]
            errors = verify_signatures(bundle)
            self.assertTrue(any("does not verify" in error for error in errors))

    def test_sign_file_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path, public_path = generate_keypair(directory)
            path = Path(directory) / "run.json"
            recorder = RunRecorder(cwd=directory, argv=["demo"])
            recorder.finalize(path)
            sign_bundle(path, private_path)
            self.assertEqual(verify_bundle(path), [])
            from proofline.storage import read_bundle

            self.assertTrue(signed_by(read_bundle(path), public_path))

    @staticmethod
    def _without_crypto() -> dict[str, None]:
        hidden = {name: None for name in list(sys.modules) if name.startswith("cryptography")}
        hidden["cryptography"] = None
        return hidden

    def test_missing_crypto_dependency_reports_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(sys.modules, self._without_crypto()):
                with self.assertRaisesRegex(RuntimeError, "proofline\\[sign\\]"):
                    generate_keypair(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_verify_reports_hint_for_signed_bundle_without_crypto(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_path, _ = generate_keypair(directory)
            bundle = sign_bundle(_bundle(directory), private_path)
            with mock.patch.dict(sys.modules, self._without_crypto()):
                errors = verify_bundle(bundle)
            self.assertEqual(errors, [MISSING_CRYPTO_HINT])


if __name__ == "__main__":
    unittest.main()
