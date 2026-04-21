from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "serve_graph_api.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_serve_graph_api", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

make_handler = _MOD.make_handler
ThreadingHTTPServer = _MOD.ThreadingHTTPServer
resolve_views_json = _MOD._resolve_views_json
parse_args = _MOD.parse_args
relation_summary_from_mention = _MOD._relation_summary_from_mention


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ServeGraphApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

        self.views = {
            "meta": {"paper_count": 1},
            "nodes": {
                "var::a": {"id": "var::a", "type": "variable", "label": "A", "name": "A"},
                "var::b": {"id": "var::b", "type": "variable", "label": "B", "name": "B"},
            },
            "edges": [
                {
                    "id": "edge::1",
                    "source": "var::a",
                    "target": "var::b",
                    "paper_id": "p1",
                    "doi": "10.1002/test",
                    "relation_type": "direct",
                    "direction": "positive",
                    "verification": "supported",
                    "strength": 1.0,
                    "evidence_anchor": "H1",
                }
            ],
            "edge_index_by_node": {"var::a": [0], "var::b": [0]},
            "overview": {"node_ids": ["var::a", "var::b"], "edge_indexes": [0]},
            "paper_map": {
                "p1": {
                    "paper_id": "p1",
                    "doi": "10.1002/test",
                    "direct_effects": [],
                    "variable_definitions": [
                        {
                            "variable": "A",
                            "definition": "A is focal antecedent.",
                            "definition_evidence_section": "Theory",
                        }
                    ],
                    "operationalization": {
                        "A": {
                            "operationalized_as": ["3-item Likert scale"]
                        }
                    },
                }
            },
        }

        class _FakeLiteratureService:
            def import_manifest(self, manifest_path: str, options: dict[str, object] | None = None) -> dict[str, object]:
                _ = options
                return {"imported_count": 1, "manifest_path": manifest_path}

            def search(
                self,
                query: str,
                top_k: int,
                levels: list[str],
                keyword_weight: float,
                rag_weight: float,
                include_expanded_context: bool,
                library_id: str = "",
            ) -> dict[str, object]:
                _ = query, top_k, levels, keyword_weight, rag_weight, include_expanded_context, library_id
                return {
                    "keyword_hits": [{"id": "k1"}],
                    "rag_hits": [{"id": "r1"}],
                    "merged_hits": [{"id": "m1"}],
                }

            def answer(
                self,
                query: str,
                top_k: int,
                levels: list[str],
                keyword_weight: float,
                rag_weight: float,
                library_id: str = "",
            ) -> dict[str, object]:
                _ = query, top_k, levels, keyword_weight, rag_weight, library_id
                return {"answer": "mock-answer", "citations": [{"id": "m1"}], "retrieval": {"merged_hits": [{"id": "m1"}]}}

        handler = make_handler(self.views, tmp_path, literature_service=_FakeLiteratureService())
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.tmp.cleanup()

    def _get_json(self, path: str) -> dict:
        with urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = __import__("urllib.request", fromlist=["Request"]).Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

    def test_graph_full_returns_all_nodes_and_edges(self) -> None:
        payload = self._get_json("/graph/full")
        self.assertIn("meta", payload)
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertIn("isolated_nodes", payload)
        self.assertIn("paper_map", payload)
        self.assertEqual(len(payload["nodes"]), 2)
        self.assertEqual(len(payload["edges"]), 1)
        self.assertEqual(payload["meta"]["dataset_library_name"], "供应链")
        self.assertEqual(payload["meta"]["isolated_node_count"], 0)
        self.assertTrue(bool(payload["nodes"][0].get("validated_variable")))
        edge = payload["edges"][0]
        self.assertEqual(edge["direction"], "positive")
        self.assertEqual(edge["verification"], "supported")
        self.assertEqual(edge["source"], "var::a")
        self.assertEqual(edge["target"], "var::b")

    def test_graph_neighborhood_returns_404_for_missing_node(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"http://127.0.0.1:{self.port}/graph/neighborhood?node_id=var::missing")
        self.assertEqual(ctx.exception.code, 404)
        body = ctx.exception.read().decode("utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["error"], "node_not_found")
        self.assertEqual(payload["node_id"], "var::missing")

    def test_paper_endpoint_accepts_url_encoded_doi(self) -> None:
        payload = self._get_json("/paper/10.1002%2Ftest")
        self.assertEqual(payload["paper_id"], "p1")
        self.assertEqual(payload["doi"], "10.1002/test")

    def test_graph_search_returns_ranked_results(self) -> None:
        payload = self._get_json("/graph/search?mode=variable&query=A&keyword_weight=1&vector_weight=0&limit=5")
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["kind"], "variable")

    def test_variable_endpoint_returns_papers(self) -> None:
        payload = self._get_json("/variable/var::a")
        self.assertEqual(payload["node"]["id"], "var::a")
        self.assertEqual(payload["paper_count"], 1)
        self.assertEqual(payload["papers"][0]["paper_id"], "p1")
        self.assertIn("paper_groups", payload)
        self.assertEqual(payload["paper_groups"][0]["paper_id"], "p1")
        self.assertEqual(payload["paper_groups"][0]["concepts"][0]["definition"], "A is focal antecedent.")
        self.assertEqual(payload["paper_groups"][0]["measurement_methods"][0]["operationalized_as"][0], "3-item Likert scale")

    def test_resolve_views_json_uses_active_pointer(self) -> None:
        tmp_path = Path(self.tmp.name)
        active_graph = tmp_path / "active_graph_views.json"
        active_graph.write_text("{}", encoding="utf-8")
        (tmp_path / "active.json").write_text(
            json.dumps({"run_id": "run_x", "graph_views": str(active_graph)}, ensure_ascii=False),
            encoding="utf-8",
        )
        resolved = resolve_views_json(None, tmp_path)
        self.assertEqual(resolved, active_graph)

    def test_parse_args_defaults_frontend_dir_to_formal_graph_page(self) -> None:
        orig_argv = sys.argv
        try:
            sys.argv = ["serve_graph_api.py"]
            args = parse_args()
        finally:
            sys.argv = orig_argv
        self.assertEqual(args.frontend_dir, Path("frontend/graph_3d"))

    def test_literature_search_endpoint_returns_two_routes_and_merged(self) -> None:
        payload = self._get_json("/literature/search?query=test&top_k=3&levels=sentence,paragraph&include_expanded_context=true")
        self.assertIn("keyword_hits", payload)
        self.assertIn("rag_hits", payload)
        self.assertIn("merged_hits", payload)

    def test_literature_import_endpoint_accepts_manifest_path(self) -> None:
        payload = self._post_json("/literature/import", {"manifest_path": "D:/tmp/manifest.jsonl"})
        self.assertEqual(payload["imported_count"], 1)
        self.assertEqual(payload["manifest_path"], "D:/tmp/manifest.jsonl")

    def test_literature_answer_endpoint_returns_answer_and_citations(self) -> None:
        payload = self._post_json("/literature/answer", {"query": "What?"})
        self.assertEqual(payload["answer"], "mock-answer")
        self.assertGreaterEqual(len(payload["citations"]), 1)

    def test_relation_summary_uses_readable_chinese_label_for_moderation(self) -> None:
        payload = relation_summary_from_mention(
            {
                "mention_kind": "moderation",
                "source_name": "Resilience",
                "target_name": "Performance",
                "moderator_name": "Institutional Support",
                "direction": "positive",
                "evidence_section": "Theory",
            }
        )
        self.assertEqual(payload["kind"], "moderation")
        self.assertIn("调节", payload["title"])
        self.assertNotIn("璋", payload["title"])


class ServeGraphApiLiteratureDegradedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
        self.views = {
            "meta": {"paper_count": 0},
            "nodes": {},
            "edges": [],
            "edge_index_by_node": {},
            "overview": {"node_ids": [], "edge_indexes": []},
            "paper_map": {},
        }

        self._orig_loader = _MOD._load_literature_service_class

        def _raise_loader():
            raise RuntimeError("synthetic_unavailable")

        _MOD._load_literature_service_class = _raise_loader
        handler = make_handler(self.views, tmp_path, literature_service=None, chat_service=object())
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        _MOD._load_literature_service_class = self._orig_loader
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.tmp.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
                raw = resp.read().decode("utf-8")
                return int(resp.status), json.loads(raw)
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            return int(exc.code), json.loads(body or "{}")

    def _post_json(self, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = __import__("urllib.request", fromlist=["Request"]).Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return int(resp.status), json.loads(raw)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return int(exc.code), json.loads(raw or "{}")

    def test_literature_search_degrades_when_service_unavailable(self) -> None:
        status, payload = self._get_json("/literature/search?query=test&top_k=3")
        self.assertEqual(status, 200)
        self.assertTrue(bool(payload.get("degraded")))
        self.assertEqual(payload.get("degraded_reason"), "literature_service_unavailable")
        self.assertEqual(payload.get("keyword_hits"), [])
        self.assertEqual(payload.get("rag_hits"), [])
        self.assertEqual(payload.get("merged_hits"), [])

    def test_literature_answer_degrades_when_service_unavailable(self) -> None:
        status, payload = self._post_json("/literature/answer", {"query": "What?"})
        self.assertEqual(status, 200)
        self.assertTrue(bool(payload.get("degraded")))
        self.assertEqual(payload.get("degraded_reason"), "literature_service_unavailable")
        self.assertIn("answer", payload)
        self.assertEqual(payload.get("citations"), [])
        self.assertEqual(payload.get("retrieval", {}).get("merged_hits"), [])


if __name__ == "__main__":
    unittest.main()

