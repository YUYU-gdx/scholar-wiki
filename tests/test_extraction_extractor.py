from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "extractor.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_extractor", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

ExtractionBundle = _MOD.ExtractionBundle
extract_records = _MOD.extract_records
parse_extraction_response = _MOD.parse_extraction_response


class _FakeSpan:
    def __init__(self, kind: str, text: str, start: int, end: int, section_title: str | None = None) -> None:
        self.kind = kind
        self.text = text
        self.start = start
        self.end = end
        self.section_title = section_title


class _FakeLLMClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response_text


class ExtractionExtractorTest(unittest.TestCase):
    def test_parse_extraction_response_returns_bundle(self) -> None:
        response_text = """
        {
          "relations": [
            {
              "source_var": "strategic flexibility",
              "target_var": "firm performance",
              "direction": "positive",
              "evidence_anchor": "Results paragraph 1"
            }
          ],
          "variable_level_theory_grounding": [
            {
              "variable": "strategic flexibility",
              "theory": "dynamic capabilities",
              "evidence_anchor": "Theory section"
            }
          ],
          "relation_level_theory_grounding": [
            {
              "source_var": "strategic flexibility",
              "target_var": "firm performance",
              "theory": "dynamic capabilities",
              "evidence_anchor": "Hypothesis 1"
            }
          ],
          "hypotheses": [
            {
              "label": "H1",
              "statement": "Strategic flexibility positively affects firm performance.",
              "verification": "supported",
              "evidence_anchor": "Results paragraph 1"
            }
          ],
          "citations": [
            {
              "source_text": "Teece (2007)",
              "citation_key": "Teece2007",
              "evidence_anchor": "Theory section"
            }
          ]
        }
        """

        bundle = parse_extraction_response(response_text)

        self.assertIsInstance(bundle, ExtractionBundle)
        self.assertEqual(bundle.relations[0]["source_var"], "strategic flexibility")
        self.assertEqual(bundle.variable_level_theory_grounding[0]["theory"], "dynamic capabilities")
        self.assertEqual(bundle.relation_level_theory_grounding[0]["target_var"], "firm performance")
        self.assertEqual(bundle.hypotheses[0]["label"], "H1")
        self.assertEqual(bundle.citations[0]["citation_key"], "Teece2007")

    def test_extract_records_calls_fake_client_and_serializes_evidence(self) -> None:
        evidence_spans = [
            _FakeSpan(
                kind="hypotheses",
                text="H1 predicts a positive relationship.",
                start=10,
                end=42,
                section_title="Hypotheses",
            ),
            _FakeSpan(
                kind="results",
                text="The main model coefficient is positive and significant.",
                start=100,
                end=170,
                section_title="Results",
            ),
        ]
        client = _FakeLLMClient(
            """
            {
              "relations": [{"source_var": "A", "target_var": "B", "direction": "positive", "evidence_anchor": "Results"}],
              "variable_level_theory_grounding": [{"variable": "A", "theory": "attention-based view", "evidence_anchor": "Hypotheses"}],
              "relation_level_theory_grounding": [{"source_var": "A", "target_var": "B", "theory": "attention-based view", "evidence_anchor": "Hypotheses"}],
              "hypotheses": [{"label": "H1", "statement": "A positively affects B.", "verification": "supported", "evidence_anchor": "Results"}],
              "citations": [{"source_text": "Ocasio (1997)", "citation_key": "Ocasio1997", "evidence_anchor": "Hypotheses"}]
            }
            """
        )

        bundle = extract_records(evidence_spans, client)

        self.assertEqual(bundle.relations[0]["target_var"], "B")
        self.assertEqual(len(client.prompts), 1)
        self.assertIn("H1 predicts a positive relationship.", client.prompts[0])
        self.assertIn("The main model coefficient is positive and significant.", client.prompts[0])
        self.assertIn('"kind": "results"', client.prompts[0])

    def test_parse_extraction_response_rejects_missing_required_sections(self) -> None:
        response_text = '{"relations": [], "hypotheses": [], "citations": []}'

        with self.assertRaises(ValueError):
            parse_extraction_response(response_text)


if __name__ == "__main__":
    unittest.main()
