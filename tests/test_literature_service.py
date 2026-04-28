from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import types


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "literature" / "service.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_literature_service", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

segment_html = _MOD.segment_html
weighted_rrf_merge = _MOD.weighted_rrf_merge
LiteratureService = _MOD.LiteratureService


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        return [[float(len(t)), 1.0] for t in texts]


class _FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, user_content: str, system_prompt: str | None = None) -> str:
        self.calls.append(user_content)
        _ = system_prompt
        return "answer-from-llm"


class _FakeWeaviateClient:
    def __init__(self) -> None:
        self.indexed: dict[str, list[dict[str, object]]] = {
            "LiteratureSentence": [],
            "LiteratureParagraph": [],
            "LiteratureDocument": [],
        }

    def ensure_literature_schema(self) -> None:
        return None

    def supports_library_id(self, refresh: bool = False) -> bool:
        _ = refresh
        return False

    def upsert(self, class_name: str, object_id: str, properties: dict[str, object], vector: list[float]) -> None:
        self.indexed[class_name].append(
            {"id": object_id, "properties": dict(properties), "vector": list(vector)}
        )

    def bm25_search(self, class_name: str, query: str, limit: int, library_id: str = "") -> list[dict[str, object]]:
        _ = class_name, query, limit, library_id
        return [
            {"id": "k-1", "score": 2.0, "properties": {"paper_id": "p-1", "sentence_id": "s-1", "text": "keyword hit"}}
        ]

    def vector_search(self, class_name: str, vector: list[float], limit: int, library_id: str = "") -> list[dict[str, object]]:
        _ = class_name, vector, limit, library_id
        return [
            {"id": "v-1", "score": 0.9, "properties": {"paper_id": "p-1", "sentence_id": "s-2", "text": "rag hit"}}
        ]


class LiteratureServiceTest(unittest.TestCase):
    def test_segment_html_builds_sentence_paragraph_document_levels(self) -> None:
        html = "<html><body><p>Alpha. Beta!</p><p>第二段第一句。第二段第二句！</p></body></html>"
        segmented = segment_html(paper_id="p1", html=html, doi="10.1/x", title="t")
        self.assertEqual(segmented["paper"]["paper_id"], "p1")
        self.assertEqual(len(segmented["paragraphs"]), 2)
        self.assertGreaterEqual(len(segmented["sentences"]), 4)
        self.assertEqual(segmented["sentences"][0]["paragraph_id"], segmented["paragraphs"][0]["paragraph_id"])

    def test_weighted_rrf_merge_returns_stable_rank(self) -> None:
        keyword_hits = [
            {"id": "a", "score": 1.0},
            {"id": "b", "score": 0.8},
        ]
        rag_hits = [
            {"id": "b", "score": 0.9},
            {"id": "c", "score": 0.7},
        ]
        merged = weighted_rrf_merge(keyword_hits, rag_hits, keyword_weight=0.4, rag_weight=0.6)
        ids = [item["id"] for item in merged]
        self.assertEqual(ids[0], "b")
        self.assertEqual(set(ids), {"a", "b", "c"})

    def test_import_search_answer_flow(self) -> None:
        fake_weaviate = _FakeWeaviateClient()
        fake_embed = _FakeEmbeddingClient()
        fake_gen = _FakeGenerator()
        service = LiteratureService(
            weaviate_client=fake_weaviate,
            embedding_client=fake_embed,
            generator_client=fake_gen,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            doc_path = tmp / "a.txt"
            doc_path.write_text("One. Two.", encoding="utf-8")
            manifest_path = tmp / "manifest.jsonl"
            manifest_path.write_text(
                json.dumps({"paper_id": "p-1", "doi": "10.1/test", "title": "Doc A", "source_path": str(doc_path)}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            import_result = service.import_manifest(manifest_path)

        self.assertEqual(import_result["imported_count"], 1)
        self.assertGreaterEqual(len(fake_weaviate.indexed["LiteratureSentence"]), 1)
        search_result = service.search(query="One", top_k=3, levels=["sentence"], keyword_weight=0.4, rag_weight=0.6, include_expanded_context=True)
        self.assertIn("keyword_hits", search_result)
        self.assertIn("rag_hits", search_result)
        self.assertIn("merged_hits", search_result)
        self.assertGreaterEqual(len(search_result["merged_hits"]), 1)
        answer_result = service.answer(query="What is this paper about?", top_k=2, levels=["sentence"], keyword_weight=0.4, rag_weight=0.6)
        self.assertEqual(answer_result["answer"], "answer-from-llm")
        self.assertGreaterEqual(len(answer_result["citations"]), 1)

    def test_import_materializes_workspace_assets(self) -> None:
        fake_weaviate = _FakeWeaviateClient()
        service = LiteratureService(
            weaviate_client=fake_weaviate,
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        old_env = {
            "LITERATURE_LIBRARY_REGISTRY_PATH": os.getenv("LITERATURE_LIBRARY_REGISTRY_PATH", ""),
            "LITERATURE_LIBRARY_INDEX_ROOT": os.getenv("LITERATURE_LIBRARY_INDEX_ROOT", ""),
            "LITERATURE_LIBRARY_WORKSPACES_ROOT": os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", ""),
        }
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp = Path(tmp_dir)
                registry_path = tmp / "registry.json"
                index_root = tmp / "index"
                workspace_root = tmp / "workspaces" / "lib_demo"
                index_root.mkdir(parents=True, exist_ok=True)
                workspace_root.mkdir(parents=True, exist_ok=True)
                (index_root / "lib_demo.json").write_text(
                    json.dumps(
                        {
                            "library_id": "lib_demo",
                            "paper_count": 0,
                            "paper_ids": [],
                            "workspace_root": str(workspace_root),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                os.environ["LITERATURE_LIBRARY_REGISTRY_PATH"] = str(registry_path)
                os.environ["LITERATURE_LIBRARY_INDEX_ROOT"] = str(index_root)
                os.environ["LITERATURE_LIBRARY_WORKSPACES_ROOT"] = str(tmp / "workspaces")

                doc_path = tmp / "source.txt"
                doc_path.write_text("Alpha paragraph.", encoding="utf-8")
                manifest_path = tmp / "manifest.jsonl"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "paper_id": "paper_demo",
                            "doi": "10.1002/SMJ.1",
                            "title": "Demo",
                            "source_path": str(doc_path),
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result = service.import_manifest(manifest_path, options={"library_id": "lib_demo"})
                self.assertEqual(result["library_id"], "lib_demo")
                self.assertEqual(result["workspace_path"], str(workspace_root.resolve()))
                self.assertEqual(len(result["materialized_papers"]), 1)
                mat = result["materialized_papers"][0]
                self.assertTrue(Path(str(mat["html_path"])).exists())
                self.assertTrue(Path(str(mat["meta_path"])).exists())
                papers_index = workspace_root / "corpus" / "index" / "papers.ndjson"
                self.assertTrue(papers_index.exists())
                lines = [x for x in papers_index.read_text(encoding="utf-8").splitlines() if x.strip()]
                self.assertEqual(len(lines), 1)
                self.assertIn("doi_10.1002_smj.1", lines[0])
                sentence_props = fake_weaviate.indexed["LiteratureSentence"][0]["properties"]
                self.assertIn("corpus", str(sentence_props.get("source_html", "")))
        finally:
            for key, value in old_env.items():
                if value:
                    os.environ[key] = value
                elif key in os.environ:
                    os.environ.pop(key, None)

    def test_import_pdf_uses_mineru_latest_folder(self) -> None:
        fake_weaviate = _FakeWeaviateClient()
        service = LiteratureService(
            weaviate_client=fake_weaviate,
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        old_env = {
            "LITERATURE_LIBRARY_REGISTRY_PATH": os.getenv("LITERATURE_LIBRARY_REGISTRY_PATH", ""),
            "LITERATURE_LIBRARY_INDEX_ROOT": os.getenv("LITERATURE_LIBRARY_INDEX_ROOT", ""),
            "LITERATURE_LIBRARY_WORKSPACES_ROOT": os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", ""),
        }
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp = Path(tmp_dir)
                registry_path = tmp / "registry.json"
                index_root = tmp / "index"
                workspace_root = tmp / "workspaces" / "lib_pdf"
                index_root.mkdir(parents=True, exist_ok=True)
                workspace_root.mkdir(parents=True, exist_ok=True)
                (index_root / "lib_pdf.json").write_text(
                    json.dumps(
                        {
                            "library_id": "lib_pdf",
                            "paper_count": 0,
                            "paper_ids": [],
                            "workspace_root": str(workspace_root),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                os.environ["LITERATURE_LIBRARY_REGISTRY_PATH"] = str(registry_path)
                os.environ["LITERATURE_LIBRARY_INDEX_ROOT"] = str(index_root)
                os.environ["LITERATURE_LIBRARY_WORKSPACES_ROOT"] = str(tmp / "workspaces")

                def _fake_mineru(src: Path, out_dir: Path) -> dict[str, object]:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / "result.html").write_text("<html><body>PDF Parsed</body></html>", encoding="utf-8")
                    return {
                        "html_text": "<html><body>PDF Parsed</body></html>",
                        "source_kind": "html",
                        "html_files": [str((out_dir / "result.html").resolve())],
                        "md_files": [],
                        "command": ["mineru"],
                    }

                service._run_mineru_to_dir = _fake_mineru  # type: ignore[method-assign]

                pdf_path = tmp / "demo.pdf"
                pdf_path.write_bytes(b"%PDF-1.4 fake")
                manifest_path = tmp / "manifest.jsonl"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "paper_id": "paper_pdf",
                            "doi": "",
                            "title": "PDF Demo",
                            "source_path": str(pdf_path),
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result = service.import_manifest(manifest_path, options={"library_id": "lib_pdf"})
                self.assertEqual(len(result["materialized_papers"]), 1)
                mat = result["materialized_papers"][0]
                self.assertTrue(Path(str(mat["source_pdf_path"])).exists())
                self.assertTrue(str(mat["source_pdf_path"]).endswith("demo.pdf"))
                self.assertTrue(Path(str(mat["mineru_output_path"])).exists())
                self.assertTrue(Path(str(mat["html_path"])).exists())
        finally:
            for key, value in old_env.items():
                if value:
                    os.environ[key] = value
                elif key in os.environ:
                    os.environ.pop(key, None)

    def test_mineru_result_named_by_first_h1(self) -> None:
        service = LiteratureService(
            weaviate_client=_FakeWeaviateClient(),
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        original_run = _MOD.subprocess.run
        try:
            def _fake_run(cmd, capture_output, text, check):  # noqa: ANN001
                out_idx = cmd.index("-o") + 1
                out_dir = Path(cmd[out_idx])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "raw.md").write_text("# My Great Paper\n\nBody", encoding="utf-8")
                return types.SimpleNamespace(returncode=0, stderr="", stdout="")

            _MOD.subprocess.run = _fake_run  # type: ignore[assignment]
            with tempfile.TemporaryDirectory() as tmp_dir:
                src_pdf = Path(tmp_dir) / "a.pdf"
                src_pdf.write_bytes(b"%PDF-1.4 test")
                out_dir = Path(tmp_dir) / "mineru_out"
                result = service._run_mineru_to_dir(src_pdf, out_dir)
                self.assertTrue(str(result["main_md_path"]).endswith("My Great Paper.md"))
                self.assertTrue(Path(str(result["main_md_path"])).exists())
        finally:
            _MOD.subprocess.run = original_run  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
