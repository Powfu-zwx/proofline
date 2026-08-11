from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from proofline import RunRecorder
from proofline.model import (
    REQUIRED_STEP,
    REQUIRED_TOP_LEVEL,
    SCHEMA_VERSION,
    STEP_KINDS,
    STEP_STATUSES,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "run.schema.json"


class SchemaConformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _record(self) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunRecorder(cwd=directory, argv=["python", "demo.py"])
            with recorder.step("model", "draft", input={"prompt": "hi"}) as step:
                step["output"] = {"text": "ok"}
                step["cost"] = {"input_tokens": 3, "output_tokens": 1}
            return recorder.finalize()

    def test_recorded_bundle_validates_against_schema(self) -> None:
        jsonschema.validate(self._record(), self.schema)

    def test_schema_rejects_missing_required_field(self) -> None:
        bundle = self._record()
        del bundle["actor"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bundle, self.schema)

    def test_schema_matches_model_constants(self) -> None:
        self.assertEqual(set(self.schema["required"]), REQUIRED_TOP_LEVEL)
        self.assertEqual(self.schema["properties"]["schema_version"]["const"], SCHEMA_VERSION)
        step_schema = self.schema["properties"]["steps"]["items"]
        self.assertEqual(set(step_schema["required"]), REQUIRED_STEP)
        self.assertEqual(set(step_schema["properties"]["kind"]["enum"]), STEP_KINDS)
        self.assertEqual(set(step_schema["properties"]["status"]["enum"]), STEP_STATUSES)


if __name__ == "__main__":
    unittest.main()
