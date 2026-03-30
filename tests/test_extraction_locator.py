from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "locator.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_locator", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

EvidenceSpan = _MOD.EvidenceSpan
locate_main_model_evidence = _MOD.locate_main_model_evidence


class ExtractionLocatorTest(unittest.TestCase):
    def test_locates_hypotheses_and_results_sections(self) -> None:
        html = """
        <section>
          <h2>Abstract</h2>
          <p>Context only.</p>
        </section>
        <section>
          <h2>Hypotheses</h2>
          <p>H1: stronger support is expected.</p>
        </section>
        <section>
          <h2>Results</h2>
          <p>The main model shows a positive effect.</p>
        </section>
        <section>
          <h2>References</h2>
          <p>Ignored.</p>
        </section>
        """

        spans = locate_main_model_evidence(html)

        self.assertEqual([span.kind for span in spans], ["hypotheses", "results"])
        self.assertTrue(all(isinstance(span, EvidenceSpan) for span in spans))
        self.assertIn("H1: stronger support is expected.", spans[0].text)
        self.assertIn("The main model shows a positive effect.", spans[1].text)

    def test_locates_main_model_table_and_stat_cell(self) -> None:
        html = """
        <section>
          <h2>Results</h2>
          <table>
            <caption>Main model estimates</caption>
            <tr><th>Variable</th><th>Beta</th><th>p</th></tr>
            <tr><td>X</td><td>0.31</td><td>p &lt; 0.05</td></tr>
          </table>
        </section>
        """

        spans = locate_main_model_evidence(html)

        self.assertGreaterEqual(len(spans), 2)
        kinds = [span.kind for span in spans]
        self.assertIn("results", kinds)
        self.assertIn("main_model_table", kinds)
        self.assertIn("main_model_stat", kinds)

        table_span = next(span for span in spans if span.kind == "main_model_table")
        stat_span = next(span for span in spans if span.kind == "main_model_stat")
        self.assertIn("Main model estimates", table_span.text)
        self.assertIn("p < 0.05", stat_span.text)
        self.assertLess(table_span.start, table_span.end)
        self.assertLess(stat_span.start, stat_span.end)

    def test_ignores_abstract_and_references_blocks(self) -> None:
        html = """
        <section>
          <h2>Abstract</h2>
          <p>Main model is mentioned only in passing.</p>
        </section>
        <section>
          <h2>References</h2>
          <p>Model citations and statistics in bibliography.</p>
        </section>
        """

        spans = locate_main_model_evidence(html)

        self.assertEqual(spans, [])


if __name__ == "__main__":
    unittest.main()
