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
          "extractability_status": "yes",
          "paper_type": "quantitative_empirical",
          "extractability_reason": "has regression",
          "extractability_evidence_section": "Methods",
          "variable_definitions": [
            {
              "variable": "strategic flexibility",
              "aliases": ["flexibility"],
              "definition": "firm strategic adaptability",
              "definition_evidence_section": "Theory"
            }
          ],
          "direct_effects": [
            {
              "source": "strategic flexibility",
              "target": "firm performance",
              "direction": "positive",
              "relation_form": "linear",
              "verification": "supported",
              "evidence_section": "Results"
            }
          ],
          "moderations": [],
          "interactions": []
        }
        """

        bundle = parse_extraction_response(response_text)

        self.assertIsInstance(bundle, ExtractionBundle)
        self.assertEqual(bundle.extractability_status, "yes")
        self.assertEqual(bundle.direct_effects[0]["source"], "strategic flexibility")
        self.assertEqual(bundle.variable_definitions[0]["variable"], "strategic flexibility")

    def test_extract_records_calls_fake_client_with_system_and_user_messages(self) -> None:
        document_html = """
        <section><h2>Hypotheses</h2><p>H1 predicts a positive relationship.</p></section>
        <section><h2>Results</h2><p>The main model coefficient is positive and significant.</p></section>
        <section><h2>References</h2><p>Some citation list should be excluded.</p></section>
        """
        client = _FakeLLMClient(
            """
            {
              "extractability_status": "yes",
              "paper_type": "quantitative_empirical",
              "extractability_reason": "has regression",
              "extractability_evidence_section": "Methods",
              "variable_definitions": [],
              "direct_effects": [{"source": "A", "target": "B", "direction": "positive", "relation_form": "linear", "verification": "supported", "evidence_section": "Results"}],
              "moderations": [],
              "interactions": []
            }
            """
        )

        bundle = extract_records(document_html, client)

        self.assertEqual(bundle.direct_effects[0]["target"], "B")
        self.assertEqual(len(client.user_contents), 1)
        self.assertEqual(len(client.system_prompts), 1)
        self.assertIn("H1 predicts a positive relationship.", client.user_contents[0])
        self.assertNotIn("Some citation list should be excluded.", client.user_contents[0])

    def test_parse_extraction_response_rejects_missing_required_sections(self) -> None:
        response_text = '{"extractability_status": "yes", "paper_type": "x"}'
        with self.assertRaises(ValueError):
            parse_extraction_response(response_text)

    def test_parse_extraction_response_rejects_direct_effect_for_non_extractable_doc(self) -> None:
        response_text = """
        {
          "extractability_status": "no",
          "paper_type": "conceptual",
          "extractability_reason": "conceptual paper",
          "extractability_evidence_section": "Abstract",
          "variable_definitions": [],
          "direct_effects": [{"source": "A", "target": "B", "direction": "positive", "relation_form": "linear", "verification": "supported", "evidence_section": "Results"}],
          "moderations": [],
          "interactions": []
        }
        """
        with self.assertRaises(ValueError):
            parse_extraction_response(response_text)

    def test_parse_extraction_response_accepts_markdown_fenced_json(self) -> None:
        response_text = """```json
{
  "extractability_status": "yes",
  "paper_type": "quantitative_empirical",
  "extractability_reason": "x",
  "extractability_evidence_section": "Methods",
  "variable_definitions": [],
  "direct_effects": [],
  "moderations": [],
  "interactions": []
}
```"""
        bundle = parse_extraction_response(response_text)
        self.assertEqual(bundle.direct_effects, [])

    def test_parse_extraction_response_keeps_moderation_target_canonical_ids(self) -> None:
        response_text = """
        {
          "extractability_status": "yes",
          "paper_type": "quantitative_empirical",
          "extractability_reason": "has regression",
          "extractability_evidence_section": "Methods",
          "variable_definitions": [],
          "direct_effects": [],
          "moderations": [
            {
              "moderator": "M",
              "direction": "positive",
              "verification": "supported",
              "evidence_section": "Results",
              "moderated_effects": [
                {
                  "source": "A short",
                  "target": "B short",
                  "source_canonical_var_id": "var::a-canonical",
                  "target_canonical_var_id": "var::b-canonical"
                }
              ]
            }
          ],
          "interactions": []
        }
        """
        bundle = parse_extraction_response(response_text)
        target = bundle.moderations[0]["moderated_effects"][0]
        self.assertEqual(target["source_canonical_var_id"], "var::a-canonical")
        self.assertEqual(target["target_canonical_var_id"], "var::b-canonical")


if __name__ == "__main__":
    unittest.main()
