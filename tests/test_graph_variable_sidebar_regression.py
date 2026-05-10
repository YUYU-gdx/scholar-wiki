from __future__ import annotations

import importlib.util
import json
import socket
import threading
import time
import unittest
from pathlib import Path
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_API_PATH = REPO_ROOT / "scripts" / "smj_pipeline" / "serve_graph_api.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(base_url: str, path: str) -> tuple[int, dict]:
    with urlopen(f"{base_url}{path}", timeout=15) as resp:
        return int(resp.status), json.loads(resp.read().decode("utf-8") or "{}")


class GraphVariableSidebarRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        graph_mod = _load_module(GRAPH_API_PATH, "smj_pipeline_serve_graph_api_for_variable_regression")
        cls.graph_mod = graph_mod

    def setUp(self) -> None:
        views = {
            "meta": {"paper_count": 1, "node_count": 2, "edge_count": 1},
            "nodes": {
                "var::A": {
                    "id": "var::A",
                    "type": "variable",
                    "label": "A",
                    "name": "A",
                    "paper_profile": {"p1": 1},
                },
                "var::B": {
                    "id": "var::B",
                    "type": "variable",
                    "label": "B",
                    "name": "B",
                },
            },
            "edges": [
                {
                    "id": "edge::1",
                    "source": "var::B",
                    "target": "var::A",
                    "paper_id": "p1",
                    "relation_type_std": "main_effect",
                    "relation_form": "positive",
                    "evidence_snippet": "evidence line",
                }
            ],
            "moderation_links": [],
            "interaction_links": [],
            "edge_index_by_node": {"var::A": [0], "var::B": [0]},
            "overview": {"node_ids": ["var::A", "var::B"], "edge_indexes": [0]},
            "paper_map": {
                "p1": {
                    "paper_id": "p1",
                    "title": "paper one",
                    "doi": "10.1002/p1",
                    # graph_views currently stores this as `variable` (not `variable_name`)
                    "variable_definitions": [{"variable": "A", "definition": "def A", "measurement": "m A"}],
                }
            },
        }
        handler = self.graph_mod.make_handler(views, REPO_ROOT)
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.server = self.graph_mod.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_variable_relations_include_theory_name_fallback(self) -> None:
        status, payload = _get_json(self.base_url, "/variable/var::A")
        self.assertEqual(status, 200)
        groups = payload.get("paper_groups") or []
        self.assertTrue(groups)
        self.assertTrue(groups[0].get("concepts"))
        relations = groups[0].get("relations") or []
        self.assertTrue(relations)
        self.assertTrue(str(relations[0].get("theory_name", "")).strip())

    def test_variable_with_only_paper_profile_still_has_source_paper(self) -> None:
        # remove connecting edge, keep paper_profile on node
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        views = {
            "meta": {"paper_count": 1, "node_count": 1, "edge_count": 0},
            "nodes": {
                "var::A": {
                    "id": "var::A",
                    "type": "variable",
                    "label": "A",
                    "name": "A",
                    "paper_profile": {"p1": 2},
                }
            },
            "edges": [],
            "moderation_links": [],
            "interaction_links": [],
            "edge_index_by_node": {"var::A": []},
            "overview": {"node_ids": ["var::A"], "edge_indexes": []},
            "paper_map": {
                "p1": {
                    "paper_id": "p1",
                    "title": "paper one",
                    "doi": "10.1002/p1",
                    "variable_definitions": [{"variable_name": "A", "definition": "def A", "measurement": "m A"}],
                }
            },
        }
        handler = self.graph_mod.make_handler(views, REPO_ROOT)
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.server = self.graph_mod.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

        status, payload = _get_json(self.base_url, "/variable/var::A")
        self.assertEqual(status, 200)
        self.assertEqual(int(payload.get("paper_count", 0)), 1)
        self.assertTrue(payload.get("papers"))
