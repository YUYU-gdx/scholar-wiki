from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "prompts.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_prompts", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

extract_domain_tags_from_html = _MOD.extract_domain_tags_from_html


class ExtractionPromptsTest(unittest.TestCase):
    def test_extract_domain_tags_from_html_uses_topics_and_keywords(self) -> None:
        html = """
        <meta name="citation_keywords" content="Strategic Management">
        <meta name="citation_keywords" content="Strategic Management">
        <script>
          window.adobeDataLayer.push({"content":{"item":{"topics":[
            {"taxonomyUri":"global-subject-codes","topicLabel":"Management"},
            {"taxonomyUri":"global-subject-codes","topicLabel":"BUSINESS \\u0026 MANAGEMENT"}
          ]}}});
        </script>
        """
        tags = extract_domain_tags_from_html(html)
        self.assertIn("Strategic Management", tags)
        self.assertIn("Management", tags)
        self.assertIn("BUSINESS & MANAGEMENT", tags)


if __name__ == "__main__":
    unittest.main()
