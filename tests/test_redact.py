from __future__ import annotations

import unittest

from proofline.redact import REDACTED, contains_unredacted_secret, redact

SECRET_VALUES = [
    "sk-abcdefghijklmnop123456",
    "ghp_abcdefghijklmnopqrst1234",
    "github_pat_11ABCDEFGHIJKLMNOPQRSTUV",
    "AKIAIOSFODNN7EXAMPLE",
    "xoxb-1234567890-abcdefghijklm",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
    "Bearer abcdefghijklmnopqrstuvwxyz",
    "-----BEGIN RSA PRIVATE KEY-----",
]


class RedactTest(unittest.TestCase):
    def test_plural_secret_keys_are_redacted(self) -> None:
        value = {"credentials": "hunter2", "secrets": {"inner": 1}, "passwords": ["x"]}
        redacted, paths = redact(value)
        self.assertEqual(
            redacted,
            {"credentials": REDACTED, "secrets": REDACTED, "passwords": REDACTED},
        )
        self.assertEqual(sorted(paths), ["/credentials", "/passwords", "/secrets"])

    def test_token_count_keys_are_not_redacted(self) -> None:
        value = {"max_tokens": 512, "total_tokens": 18, "tokens": 3, "session_token": "abc"}
        redacted, paths = redact(value)
        self.assertEqual(redacted["max_tokens"], 512)
        self.assertEqual(redacted["total_tokens"], 18)
        self.assertEqual(redacted["tokens"], 3)
        self.assertEqual(redacted["session_token"], REDACTED)
        self.assertEqual(paths, ["/session_token"])

    def test_secret_value_patterns_are_redacted(self) -> None:
        for secret in SECRET_VALUES:
            with self.subTest(secret=secret):
                redacted, paths = redact({"note": f"value {secret} end"})
                self.assertEqual(redacted["note"], REDACTED)
                self.assertEqual(paths, ["/note"])

    def test_leak_scan_matches_redaction_patterns(self) -> None:
        for secret in SECRET_VALUES:
            with self.subTest(secret=secret):
                self.assertEqual(contains_unredacted_secret({"note": secret}), ["/note"])

    def test_pointer_escaping_for_special_keys(self) -> None:
        redacted, paths = redact({"a/b_token": "x"})
        self.assertEqual(redacted["a/b_token"], REDACTED)
        self.assertEqual(paths, ["/a~1b_token"])

    def test_plain_values_pass_through(self) -> None:
        value = {"text": "hello world", "count": 3, "flag": True, "nothing": None}
        redacted, paths = redact(value)
        self.assertEqual(redacted, value)
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
