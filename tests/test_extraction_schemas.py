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

DirectEffectSchema = _MOD.DirectEffectSchema


class ExtractionSchemasTest(unittest.TestCase):
    def test_valid_direct_effect_schema(self) -> None:
        schema = DirectEffectSchema(
            source="A",
            target="B",
            direction="positive",
            relation_form="linear",
            verification="supported",
            evidence_section="Results",
        )
        self.assertEqual(schema.source, "A")

    def test_rejects_unknown_direction(self) -> None:
        with self.assertRaises(ValueError):
            DirectEffectSchema(
                source="A",
                target="B",
                direction="neutral",
                relation_form="linear",
                verification="supported",
                evidence_section="Results",
            )

    def test_rejects_unknown_verification(self) -> None:
        with self.assertRaises(ValueError):
            DirectEffectSchema(
                source="A",
                target="B",
                direction="positive",
                relation_form="linear",
                verification="partially_supported",
                evidence_section="Results",
            )

    def test_rejects_empty_evidence_section(self) -> None:
        with self.assertRaises(ValueError):
            DirectEffectSchema(
                source="A",
                target="B",
                direction="positive",
                relation_form="linear",
                verification="supported",
                evidence_section="   ",
            )


if __name__ == "__main__":
    unittest.main()
