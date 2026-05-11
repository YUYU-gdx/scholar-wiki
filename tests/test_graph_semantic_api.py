from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kn_graph.routers import graph as graph_router


class _FakeVariableConceptIndexService:
    def __init__(self, workspace_path: str = "") -> None:
        self.workspace_path = workspace_path

    def query(self, library_id: str, query: str, top_k: int = 5):
        return [
            {
                "id": f"{library_id}::doc1",
                "score": 0.91,
                "library_id": library_id,
                "paper_id": "p1",
                "variable_name": "Resilience",
                "canonical_var_id": "cv_resilience",
                "concept_text": f"{query} concept",
            }
        ][:top_k]


class _FakeGraphService:
    def __init__(self, root: Path) -> None:
        self._settings = type("S", (), {"workspaces_dir": root})()

    def get_overview(self, library_id: str = ""):
        return {"ok": True}

    def get_full(self, library_id: str = ""):
        return {"ok": True}

    def reload(self, library_id: str = ""):
        return {"ok": True}

    def search(self, **kwargs):
        return {"results": [{"id": "var::resilience", "title": "Resilience", "library_id": kwargs.get("library_id", "")}]}

    def get_neighborhood(self, node_id: str, **kwargs):
        return {
            "nodes": [
                {"id": "var::resilience", "label": "Resilience", "type": "variable"},
                {"id": "var::risk", "label": "Risk", "type": "variable"},
                {"id": "var::performance", "label": "Performance", "type": "variable"},
            ],
            "edges": [
                {"source": "var::risk", "target": "var::resilience"},
                {"source": "var::resilience", "target": "var::performance"},
            ],
        }

    def get_variable(self, node_id: str, library_id: str = ""):
        concept = {
            "var::resilience": "resilience concept",
            "var::risk": "risk concept",
            "var::performance": "performance concept",
        }.get(node_id, "")
        return {
            "paper_groups": [
                {
                    "concepts": [{"definition": concept}],
                }
            ]
        }


class TestGraphSemanticApi(unittest.TestCase):
    def test_semantic_search_and_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = FastAPI()
            fake_graph = _FakeGraphService(Path(tmp))
            original_cls = graph_router.VariableConceptIndexService
            graph_router.VariableConceptIndexService = _FakeVariableConceptIndexService
            try:
                app.include_router(graph_router.create_router(fake_graph))
                client = TestClient(app)

                search_resp = client.post(
                    "/graph/semantic-variables/search",
                    json={"query": "supply chain resilience", "top_k": 5, "library_ids": ["lib_a"]},
                )
                self.assertEqual(search_resp.status_code, 200)
                payload = search_resp.json()
                self.assertTrue(payload.get("ok"))
                self.assertEqual(len(payload.get("matched_variables") or []), 1)

                neighbors_resp = client.post(
                    "/graph/semantic-variables/neighbors",
                    json={"variable_name": "Resilience", "top_k": 5, "library_ids": ["lib_a"]},
                )
                self.assertEqual(neighbors_resp.status_code, 200)
                n_payload = neighbors_resp.json()
                self.assertTrue(n_payload.get("ok"))
                rows = n_payload.get("results") or []
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertGreaterEqual(len(row.get("cause_variables") or []), 1)
                self.assertGreaterEqual(len(row.get("effect_variables") or []), 1)
            finally:
                graph_router.VariableConceptIndexService = original_cls


if __name__ == "__main__":
    unittest.main()
