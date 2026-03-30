from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "storage" / "neo4j_repo.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_storage_neo4j_repo", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

Neo4jRepo = _MOD.Neo4jRepo


def _bundle() -> dict[str, list[dict[str, str]]]:
    return {
        "relations": [
            {
                "source_var": "A",
                "target_var": "B",
                "relation_type": "direct",
                "model_tag": "main_model",
                "direction": "positive",
                "verification": "supported",
            }
        ],
        "variable_level_theory_grounding": [
            {
                "variable": "A",
                "theory": "dynamic capabilities",
            }
        ],
        "relation_level_theory_grounding": [
            {
                "source_var": "A",
                "target_var": "B",
                "theory": "dynamic capabilities",
            }
        ],
        "hypotheses": [
            {
                "label": "H1",
                "statement": "A positively affects B.",
                "verification": "supported",
            }
        ],
        "citations": [
            {
                "citation_key": "Teece2007",
                "source_text": "Teece (2007)",
            }
        ],
    }


class _FakeSession:
    def __init__(self, calls: list[tuple[str, dict[str, object]]]) -> None:
        self.calls = calls

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, query: str, **parameters: object) -> None:
        self.calls.append((query, parameters))


class _FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def session(self) -> _FakeSession:
        return _FakeSession(self.calls)


class Neo4jRepoTest(unittest.TestCase):
    def test_project_bundle_emits_queries_for_relations_theory_hypotheses_and_citations(self) -> None:
        driver = _FakeDriver()
        repo = Neo4jRepo(driver)

        repo.project_bundle("paper-1", _bundle())

        self.assertEqual(len(driver.calls), 5)
        queries = [query for query, _ in driver.calls]
        params = [parameters for _, parameters in driver.calls]

        self.assertTrue(any("MENTIONS_RELATION" in query for query in queries))
        self.assertTrue(any("GROUNDED_IN" in query for query in queries))
        self.assertTrue(any("SUPPORTS_HYPOTHESIS" in query for query in queries))
        self.assertTrue(any("CITES" in query for query in queries))
        self.assertTrue(all(parameters["paper_id"] == "paper-1" for parameters in params))
        relation_params = next(parameters for query, parameters in driver.calls if "MENTIONS_RELATION" in query)
        self.assertEqual(relation_params["source_var"], "A")
        self.assertEqual(relation_params["target_var"], "B")
        self.assertEqual(relation_params["direction"], "positive")


if __name__ == "__main__":
    unittest.main()
