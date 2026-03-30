from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "schemas.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_schemas", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

ExtractionSchema = _MOD.ExtractionSchema


class ExtractionSchemasTest(unittest.TestCase):
    def test_valid_schema(self) -> None:
        schema = ExtractionSchema(
            model_tag="main_model",
            direction="positive",
            verification="supported",
            evidence_anchor="method section",
        )
        self.assertEqual(schema.model_tag, "main_model")

    def test_rejects_wrong_model_tag(self) -> None:
        with self.assertRaises(ValueError):
            ExtractionSchema(
                model_tag="secondary_model",
                direction="positive",
                verification="supported",
                evidence_anchor="method section",
            )

    def test_rejects_unknown_direction(self) -> None:
        with self.assertRaises(ValueError):
            ExtractionSchema(
                model_tag="main_model",
                direction="neutral",
                verification="supported",
                evidence_anchor="method section",
            )

    def test_rejects_unknown_verification(self) -> None:
        with self.assertRaises(ValueError):
            ExtractionSchema(
                model_tag="main_model",
                direction="positive",
                verification="unclear",
                evidence_anchor="method section",
            )

    def test_rejects_empty_evidence_anchor(self) -> None:
        with self.assertRaises(ValueError):
            ExtractionSchema(
                model_tag="main_model",
                direction="positive",
                verification="supported",
                evidence_anchor="   ",
            )


if __name__ == "__main__":
    unittest.main()
