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


class _FakeLLMClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.user_contents: list[str] = []
        self.system_prompts: list[str] = []

    def complete(self, user_content: str, system_prompt: str | None = None) -> str:
        self.user_contents.append(user_content)
        self.system_prompts.append(system_prompt or "")
        return self.response_text


class ExtractionExtractorTest(unittest.TestCase):
    def test_parse_extraction_response_returns_bundle(self) -> None:
        response_text = """
        {
          "relations": [
            {
              "source_var": "strategic flexibility",
              "target_var": "firm performance",
              "relation_type": "direct",
              "model_tag": "main_model",
              "direction": "positive",
              "verification": "supported",
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
        self.assertEqual(bundle.paper_domains, [])

    def test_extract_records_calls_fake_client_with_system_and_user_messages(self) -> None:
        document_html = """
        <section><h2>Hypotheses</h2><p>H1 predicts a positive relationship.</p></section>
        <section><h2>Results</h2><p>The main model coefficient is positive and significant.</p></section>
        <section><h2>References</h2><p>Some citation list should be excluded.</p></section>
        """
        client = _FakeLLMClient(
            """
            {
              "relations": [{"source_var": "A", "target_var": "B", "relation_type":"direct", "model_tag":"main_model", "direction": "positive", "verification":"supported", "evidence_anchor": "Results"}],
              "variable_level_theory_grounding": [{"variable": "A", "theory": "attention-based view", "evidence_anchor": "Hypotheses"}],
              "relation_level_theory_grounding": [{"source_var": "A", "target_var": "B", "theory": "attention-based view", "evidence_anchor": "Hypotheses"}],
              "hypotheses": [{"label": "H1", "statement": "A positively affects B.", "verification": "supported", "evidence_anchor": "Results"}],
              "citations": [{"source_text": "Ocasio (1997)", "citation_key": "Ocasio1997", "evidence_anchor": "Hypotheses"}]
            }
            """
        )

        bundle = extract_records(document_html, client)

        self.assertEqual(bundle.relations[0]["target_var"], "B")
        self.assertEqual(len(client.user_contents), 1)
        self.assertEqual(len(client.system_prompts), 1)
        self.assertIn("H1 predicts a positive relationship.", client.user_contents[0])
        self.assertIn("The main model coefficient is positive and significant.", client.user_contents[0])
        self.assertNotIn("Some citation list should be excluded.", client.user_contents[0])
        self.assertIn('"relations"', client.system_prompts[0])

    def test_parse_extraction_response_rejects_missing_required_sections(self) -> None:
        response_text = '{"relations": [], "hypotheses": [], "citations": []}'

        with self.assertRaises(ValueError):
            parse_extraction_response(response_text)

    def test_parse_extraction_response_rejects_invalid_relation_semantics(self) -> None:
        response_text = """
        {
          "relations": [{"source_var": "A", "target_var": "B", "relation_type": "direct", "model_tag": "robustness", "direction": "positive", "verification": "supported", "evidence_anchor": "x"}],
          "variable_level_theory_grounding": [],
          "relation_level_theory_grounding": [],
          "hypotheses": [],
          "citations": []
        }
        """
        with self.assertRaises(ValueError):
            parse_extraction_response(response_text)

    def test_parse_extraction_response_accepts_markdown_fenced_json(self) -> None:
        response_text = """```json
{
  "relations": [],
  "variable_level_theory_grounding": [],
  "relation_level_theory_grounding": [],
  "hypotheses": [],
  "citations": []
}
```"""
        bundle = parse_extraction_response(response_text)
        self.assertEqual(bundle.relations, [])

    def test_parse_extraction_response_accepts_text_wrapped_json(self) -> None:
        response_text = """
Here is the extracted payload:
{
  "relations": [],
  "variable_level_theory_grounding": [],
  "relation_level_theory_grounding": [],
  "hypotheses": [],
  "citations": []
}
"""
        bundle = parse_extraction_response(response_text)
        self.assertEqual(bundle.citations, [])

    def test_parse_extraction_response_backfills_alias_and_canonical_fields(self) -> None:
        response_text = """
        {
          "relations": [
            {"source_var": "A", "target_var": "B", "relation_type": "direct", "model_tag": "main_model", "direction": "inverted_u", "verification": "supported", "evidence_anchor": "t1"}
          ],
          "variable_level_theory_grounding": [],
          "relation_level_theory_grounding": [],
          "hypotheses": [],
          "citations": []
        }
        """
        bundle = parse_extraction_response(response_text)
        rel = bundle.relations[0]
        self.assertEqual(rel["source_aliases"], ["A"])
        self.assertEqual(rel["target_aliases"], ["B"])
        self.assertTrue(rel["source_canonical_var_id"].startswith("var::"))
        self.assertEqual(rel["relation_form"], "nonlinear")

    def test_extract_records_prefers_html_metadata_domains(self) -> None:
        document_html = """
        <meta name="citation_keywords" content="Strategic Management">
        <script>
        window.adobeDataLayer.push({"content":{"item":{"topics":[{"taxonomyUri":"global-subject-codes","topicLabel":"Management"}]}}});
        </script>
        <section><h2>Hypotheses</h2><p>H1 predicts a positive relationship.</p></section>
        """
        client = _FakeLLMClient(
            """
            {
              "paper_domains": ["fallback-domain"],
              "relations": [],
              "variable_level_theory_grounding": [],
              "relation_level_theory_grounding": [],
              "hypotheses": [],
              "citations": []
            }
            """
        )
        bundle = extract_records(document_html, client)
        self.assertIn("Strategic Management", bundle.paper_domains)
        self.assertIn("Management", bundle.paper_domains)

    def test_parse_extraction_response_resolves_full_name_from_aliases(self) -> None:
        response_text = """
        {
          "relations": [
            {
              "source_var": "TMT",
              "target_var": "firm performance",
              "source_aliases": ["Top management team (TMT)"],
              "target_aliases": ["firm performance"],
              "relation_type": "direct",
              "model_tag": "main_model",
              "direction": "positive",
              "verification": "supported",
              "evidence_anchor": "Hypothesis testing"
            }
          ],
          "variable_level_theory_grounding": [],
          "relation_level_theory_grounding": [],
          "hypotheses": [],
          "citations": []
        }
        """
        bundle = parse_extraction_response(response_text)
        rel = bundle.relations[0]
        self.assertEqual(rel["source_var"], "Top management team")
        self.assertFalse(rel["unresolved_abbr"])
        self.assertEqual(rel["name_resolution_source"], "postprocess")
        self.assertIn("TMT", rel["source_aliases"])

    def test_parse_extraction_response_marks_unresolved_abbreviation(self) -> None:
        response_text = """
        {
          "relations": [
            {
              "source_var": "TMT",
              "target_var": "firm performance",
              "relation_type": "direct",
              "model_tag": "main_model",
              "direction": "positive",
              "verification": "supported",
              "evidence_anchor": "Hypothesis testing"
            }
          ],
          "variable_level_theory_grounding": [],
          "relation_level_theory_grounding": [],
          "hypotheses": [],
          "citations": []
        }
        """
        bundle = parse_extraction_response(response_text)
        rel = bundle.relations[0]
        self.assertEqual(rel["source_var"], "TMT")
        self.assertTrue(rel["unresolved_abbr"])
        self.assertEqual(rel["abbr_form"], "TMT")
        self.assertEqual(rel["name_resolution_source"], "fallback")


if __name__ == "__main__":
    unittest.main()
