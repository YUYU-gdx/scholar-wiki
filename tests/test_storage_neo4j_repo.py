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


def _bundle() -> dict[str, object]:
    return {
        "extractability_status": "yes",
        "paper_type": "quantitative_empirical",
        "direct_effects": [
            {
                "source": "A",
                "target": "B",
                "direction": "positive",
                "relation_form": "linear",
                "verification": "supported",
                "evidence_section": "Results",
            }
        ],
        "moderations": [
            {
                "moderator": "M",
                "moderated_effects": [{"source": "A", "target": "B"}],
                "direction": "positive",
                "verification": "supported",
                "evidence_section": "Results",
            }
        ],
        "interactions": [],
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
    def test_project_bundle_emits_queries_for_new_payload(self) -> None:
        driver = _FakeDriver()
        repo = Neo4jRepo(driver)
        repo.project_bundle("paper-1", _bundle())

        queries = [q for q, _ in driver.calls]
        self.assertTrue(any("DIRECT_EFFECT" in q for q in queries))
        self.assertTrue(any("MODERATES" in q for q in queries))
        self.assertTrue(all(p["paper_id"] == "paper-1" for _, p in driver.calls))


if __name__ == "__main__":
    unittest.main()

