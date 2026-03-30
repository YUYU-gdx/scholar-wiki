from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "qualifier.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_qualifier", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

classify_document = _MOD.classify_document


class ExtractionQualifierTest(unittest.TestCase):
    def test_abstract_only_is_class_b(self) -> None:
        html = "<section>Abstract</section><section>References</section>"
        result = classify_document(html)
        self.assertEqual(result.doc_class, "B")

    def test_hypotheses_and_main_model_signal_is_class_a(self) -> None:
        html = """
        <section>Abstract</section>
        <section>Hypotheses</section>
        <section>Results</section>
        <table><tr><td>Main model</td><td>beta = 0.31, p < 0.05</td></tr></table>
        <section>References</section>
        """
        result = classify_document(html)
        self.assertEqual(result.doc_class, "A")
        self.assertTrue(result.has_hypotheses_block)
        self.assertTrue(result.has_results_block)
        self.assertTrue(result.has_main_model_signal)

    def test_other_documents_are_class_c(self) -> None:
        html = "<section>Introduction</section><section>Discussion</section>"
        result = classify_document(html)
        self.assertEqual(result.doc_class, "C")


if __name__ == "__main__":
    unittest.main()
