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
                "extractable_yes_docs": 80,
                "direct_effects_total": 120,
                "moderations_total": 40,
                "validated_direct_effects": 100,
            }
        )
        self.assertEqual(
            result,
            MetricsResult(
                extractable_rate=0.8,
                mean_direct_effects_per_doc=1.2,
                mean_moderations_per_doc=0.4,
                direct_effect_validation_rate=100 / 120,
            ),
        )

    def test_calculate_metrics_handles_zero_denominator(self) -> None:
        result = calculate_metrics({})
        self.assertEqual(result.extractable_rate, 0.0)
        self.assertEqual(result.mean_direct_effects_per_doc, 0.0)
        self.assertEqual(result.mean_moderations_per_doc, 0.0)
        self.assertEqual(result.direct_effect_validation_rate, 0.0)

    def test_render_report_uses_template(self) -> None:
        report = render_report(
            MetricsResult(
                extractable_rate=0.8,
                mean_direct_effects_per_doc=1.2,
                mean_moderations_per_doc=0.4,
                direct_effect_validation_rate=0.9,
            ),
            {"run_id": "r-001", "sample_size": 100},
        )
        self.assertIn("Run ID: `r-001`", report)
        self.assertIn("Extractable rate: `80.00%`", report)
        self.assertIn("Direct-effect validation rate: `90.00%`", report)


if __name__ == "__main__":
    unittest.main()
