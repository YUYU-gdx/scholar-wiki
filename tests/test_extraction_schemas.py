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


class ExtractionSchemasTest(unittest.TestCase):
    def test_effect_form_allowed_values(self) -> None:
        self.assertIn("positive", _MOD.ALLOWED_EFFECT_FORM)
        self.assertIn("negative", _MOD.ALLOWED_EFFECT_FORM)
        self.assertIn("nonlinear", _MOD.ALLOWED_EFFECT_FORM)
        self.assertIn("unclear", _MOD.ALLOWED_EFFECT_FORM)
        self.assertNotIn("neutral", _MOD.ALLOWED_EFFECT_FORM)

    def test_verification_allowed_values(self) -> None:
        self.assertIn("supported", _MOD.ALLOWED_VERIFICATION)
        self.assertIn("not_supported", _MOD.ALLOWED_VERIFICATION)
        self.assertIn("mixed", _MOD.ALLOWED_VERIFICATION)
        self.assertIn("unclear", _MOD.ALLOWED_VERIFICATION)
        self.assertNotIn("partially_supported", _MOD.ALLOWED_VERIFICATION)

    def test_extractability_status_allowed_values(self) -> None:
        self.assertIn("yes", _MOD.ALLOWED_EXTRACTABILITY_STATUS)
        self.assertIn("no", _MOD.ALLOWED_EXTRACTABILITY_STATUS)
        self.assertIn("uncertain", _MOD.ALLOWED_EXTRACTABILITY_STATUS)


if __name__ == "__main__":
    unittest.main()
