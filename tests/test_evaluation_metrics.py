from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "evaluation" / "metrics.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_evaluation_metrics", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

MetricsResult = _MOD.MetricsResult
calculate_metrics = _MOD.calculate_metrics
render_report = _MOD.render_report


class EvaluationMetricsTest(unittest.TestCase):
    def test_calculate_metrics_nominal(self) -> None:
        result = calculate_metrics(
            {
                "eligible_docs": 100,
                "extracted_relations": 80,
                "complete_relations": 72,
                "hypotheses_total": 50,
                "hypotheses_correct": 45,
                "relations_with_theory": 60,
                "citations_total": 40,
                "citations_locatable": 30,
            }
        )
        self.assertEqual(
            result,
            MetricsResult(
                relation_coverage=0.8,
                field_completeness=0.9,
                hypothesis_verification_accuracy=0.9,
                theory_traceability=0.75,
                citation_locatability=0.75,
            ),
        )

    def test_calculate_metrics_handles_zero_denominator(self) -> None:
        result = calculate_metrics({})
        self.assertEqual(result.relation_coverage, 0.0)
        self.assertEqual(result.field_completeness, 0.0)
        self.assertEqual(result.hypothesis_verification_accuracy, 0.0)
        self.assertEqual(result.theory_traceability, 0.0)
        self.assertEqual(result.citation_locatability, 0.0)

    def test_render_report_uses_template_and_formats_percentages(self) -> None:
        report = render_report(
            MetricsResult(
                relation_coverage=0.8,
                field_completeness=0.9,
                hypothesis_verification_accuracy=0.9,
                theory_traceability=0.75,
                citation_locatability=0.75,
            ),
            {"run_id": "r-001", "sample_size": 100},
        )
        self.assertIn("Run ID: `r-001`", report)
        self.assertIn("Sample Size (Class A denominator): `100`", report)
        self.assertIn("Relation coverage: `80.00%`", report)
        self.assertIn("Field completeness: `90.00%`", report)
        self.assertIn("Hypothesis verification accuracy: `90.00%`", report)
        self.assertIn("Theory traceability: `75.00%`", report)
        self.assertIn("Citation locatability: `75.00%`", report)


if __name__ == "__main__":
    unittest.main()
