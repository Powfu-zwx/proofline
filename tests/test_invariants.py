"""Cross-module invariants that individual unit tests do not pin down."""

from __future__ import annotations

import random
import tempfile
import unittest

from proofline import RunRecorder, verify_bundle
from proofline.model import StableDigestBuilder, canonical_json, stable_bundle, stable_digest
from proofline.redact import redact


class InvariantTest(unittest.TestCase):
    def test_canonical_json_ignores_key_insertion_order(self) -> None:
        left = {"b": 1, "a": {"y": [1, {"k": 2}], "x": 3}}
        right = {"a": {"x": 3, "y": [1, {"k": 2}]}, "b": 1}
        self.assertEqual(canonical_json(left), canonical_json(right))

    def test_canonical_json_rejects_non_strict_json(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_json({"cost": value})

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


def _random_json_value(rng: random.Random, depth: int = 0) -> object:
    choice = rng.randrange(7 if depth < 3 else 4)
    if choice == 0:
        return rng.randint(-10**6, 10**6)
    if choice == 1:
        return rng.choice(["", "hello", "héllo", "a/b~c", "Bearer abcdefghijklmnopqr"])
    if choice == 2:
        return rng.choice([None, True, False])
    if choice == 3:
        return round(rng.uniform(-100, 100), 3)
    if choice == 4:
        return {
            rng.choice("abcdefg"): _random_json_value(rng, depth + 1)
            for _ in range(rng.randrange(3))
        }
    if choice == 5:
        return [_random_json_value(rng, depth + 1) for _ in range(rng.randrange(3))]
    return rng.choice([{}, []])


def _random_step(rng: random.Random) -> dict:
    step = {
        "step_id": f"step-{rng.randrange(5)}",
        "kind": rng.choice(["model", "tool", "custom"]),
        "name": rng.choice(["draft", "call", "run"]),
        "status": rng.choice(["ok", "error"]),
        "started_at": "2026-01-01T00:00:00.000Z",
        "ended_at": "2026-01-01T00:00:01.000Z",
        "input": _random_json_value(rng),
        "output": _random_json_value(rng),
    }
    if rng.random() < 0.5:
        step["cost"] = {"input_tokens": rng.randrange(100)}
    return step


def _random_bundle(rng: random.Random) -> dict:
    steps = [_random_step(rng) for _ in range(rng.randrange(5))]
    bundle: dict = {"schema_version": "0.1", "steps": steps}
    for field in ("run_id", "created_at", "bundle_digest", "signatures"):
        if rng.random() < 0.5:
            bundle[field] = "volatile"
    if rng.random() < 0.7:
        bundle["metadata"] = {"k": _random_json_value(rng)}
    if rng.random() < 0.7:
        keep = set(rng.sample(["a", "b", "c"], rng.randrange(4)))
        bundle["redactions"] = sorted(keep)
    return bundle


class DigestStreamingInvariant(unittest.TestCase):
    def test_streaming_digest_equals_stable_digest(self) -> None:
        """The journal's incremental digest must be bit-identical to stable_digest."""
        rng = random.Random(20260815)
        for _ in range(50):
            bundle = _random_bundle(rng)
            header = {key: value for key, value in stable_bundle(bundle).items() if key != "steps"}
            builder = StableDigestBuilder(header)
            for step in bundle["steps"]:
                builder.add_step(step)
            with self.subTest(bundle=canonical_json(bundle)[:80]):
                self.assertEqual(builder.hexdigest(), stable_digest(bundle))


if __name__ == "__main__":
    unittest.main()
