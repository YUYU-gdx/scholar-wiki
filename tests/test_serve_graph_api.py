from __future__ import annotations

import importlib.util
import json
import os
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
        self._old_codex_cfg = os.environ.get("CHAT_CODEX_CONFIG_PATH")
        os.environ["CHAT_CODEX_CONFIG_PATH"] = str(tmp_path / "codex_runner_config.json")
        (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
        workbench_dir = tmp_path / "workbench"
        workbench_dir.mkdir(parents=True, exist_ok=True)
        (workbench_dir / "index.html").write_text("<html><body data-testid='workbench-marker'>workbench</body></html>", encoding="utf-8")

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

        class _FakeWorkspaceLayoutStore:
            def __init__(self) -> None:
                self.items: dict[str, dict[str, object]] = {}

            def list_layouts(self) -> dict[str, object]:
                return {"layouts": [{"name": k, "updated_at": "now"} for k in sorted(self.items.keys())]}

            def get_layout(self, name: str = "default") -> dict[str, object] | None:
                row = self.items.get(name)
                if row is None:
                    return None
                return {"name": name, "layout": row.get("layout", {}), "updated_at": "now"}

            def save_layout(self, name: str, layout: dict[str, object]) -> dict[str, object]:
                self.items[name] = {"layout": layout}
                return {"name": name, "layout": layout, "updated_at": "now"}

        self.workspace_store = _FakeWorkspaceLayoutStore()
        handler = make_handler(
            self.views,
            tmp_path,
            workbench_frontend_dir=workbench_dir,
            literature_service=_FakeLiteratureService(),
            workspace_layout_store=self.workspace_store,
        )
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        if self._old_codex_cfg is None:
            os.environ.pop("CHAT_CODEX_CONFIG_PATH", None)
        else:
            os.environ["CHAT_CODEX_CONFIG_PATH"] = self._old_codex_cfg
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
        self.assertEqual(args.workbench_frontend_dir, Path("frontend/workbench_spa"))

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

    def test_literature_libraries_endpoint_scans_index_root(self) -> None:
        libraries_root = Path(self.tmp.name) / "libraries"
        libraries_root.mkdir(parents=True, exist_ok=True)
        (libraries_root / "lib_a.json").write_text(
            json.dumps(
                {
                    "library_id": "lib_a",
                    "paper_count": 12,
                    "updated_at": "2026-04-22 10:00:00",
                    "paper_ids": ["p1", "p2"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (libraries_root / "invalid.json").write_text("{not-json", encoding="utf-8")
        old_val = os.environ.get("LITERATURE_LIBRARY_INDEX_ROOT")
        os.environ["LITERATURE_LIBRARY_INDEX_ROOT"] = str(libraries_root)
        try:
            payload = self._get_json("/literature/libraries")
        finally:
            if old_val is None:
                os.environ.pop("LITERATURE_LIBRARY_INDEX_ROOT", None)
            else:
                os.environ["LITERATURE_LIBRARY_INDEX_ROOT"] = old_val
        self.assertIn("libraries", payload)
        self.assertEqual(len(payload["libraries"]), 1)
        self.assertEqual(payload["libraries"][0]["library_id"], "lib_a")
        self.assertIn("workspace_path", payload["libraries"][0])
        self.assertEqual(payload["default_library_id"], "lib_a")

    def test_workspace_layout_api_supports_save_get_and_list(self) -> None:
        saved = self._post_json("/api/v2/workspace/layout", {"name": "demo", "layout": {"content": [{"type": "row"}]}})
        self.assertEqual(saved["name"], "demo")
        self.assertIn("layout", saved)
        fetched = self._get_json("/api/v2/workspace/layout?name=demo")
        self.assertEqual(fetched["name"], "demo")
        self.assertIn("content", fetched["layout"])
        listed = self._get_json("/api/v2/workspace/layouts")
        names = [str(x.get("name", "")) for x in listed.get("layouts", [])]
        self.assertIn("demo", names)

    def test_codex_config_endpoint_supports_get_and_save(self) -> None:
        got = self._get_json("/chat/codex/config")
        self.assertIn("config", got)
        payload = {
            "cli_command": "codex",
            "cli_args": ["exec", "--cwd", "{workdir}", "{prompt}"],
            "healthcheck_args": ["--version"],
            "timeout_seconds": 120,
            "install_command": "npm install -g @openai/codex",
            "extra_env": {"A": "B"},
        }
        saved = self._post_json("/chat/codex/config", payload)
        self.assertTrue(bool(saved.get("ok")))
        got2 = self._get_json("/chat/codex/config")
        cfg = got2.get("config", {})
        self.assertEqual(cfg.get("cli_command"), "codex")
        self.assertEqual(cfg.get("timeout_seconds"), 120)

    def test_workbench_frontend_entry_is_served(self) -> None:
        with urlopen(f"http://127.0.0.1:{self.port}/frontend/workbench/") as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        self.assertIn("workbench-marker", html)

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


class ServeGraphApiWorkspaceFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
        views = {
            "meta": {"paper_count": 0},
            "nodes": {},
            "edges": [],
            "edge_index_by_node": {},
            "overview": {"node_ids": [], "edge_indexes": []},
            "paper_map": {},
        }
        self._orig_workspace_loader = _MOD._load_workspace_layout_store_class

        def _raise_loader():
            raise RuntimeError("synthetic_workspace_loader_error")

        _MOD._load_workspace_layout_store_class = _raise_loader
        handler = make_handler(views, tmp_path, literature_service=object(), chat_service=object(), workspace_layout_store=None)
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        _MOD._load_workspace_layout_store_class = self._orig_workspace_loader
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

    def test_workspace_layout_routes_work_with_in_memory_fallback(self) -> None:
        status, listed = self._get_json("/api/v2/workspace/layouts")
        self.assertEqual(status, 200)
        self.assertTrue(bool(listed.get("degraded")))
        self.assertIn("degraded_reason", listed)

        status, saved = self._post_json("/api/v2/workspace/layout", {"name": "default", "layout": {"nodes": []}})
        self.assertEqual(status, 200)
        self.assertTrue(bool(saved.get("degraded")))
        self.assertEqual(saved.get("name"), "default")

        status, loaded = self._get_json("/api/v2/workspace/layout?name=default")
        self.assertEqual(status, 200)
        self.assertTrue(bool(loaded.get("degraded")))
        self.assertEqual(loaded.get("name"), "default")


if __name__ == "__main__":
    unittest.main()

