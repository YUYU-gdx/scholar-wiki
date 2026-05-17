from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kn_graph.services.literature_service import (
    ChromaDBClient,
    LiteratureService,
    segment_html,
    weighted_rrf_merge,
)


class _FakeSettings:
    literature_default_library_id: str = ""
    literature_library_index_root: str = "outputs/literature_libraries"
    literature_library_registry_path: str = ""
    literature_library_workspaces_root: str = ""
    literature_embedding_model: str = "embedding-3"
    literature_chat_model: str = "glm-4.5-flash"
    literature_embed_max_chars: int = 8000
    literature_embed_batch_size: int = 32
    zhipu_api_key: str = ""
    mineru_api_key: str = ""
    mineru_version: str = ""
    registry_path: str = ""
    indexes_dir: str = ""
    workspaces_dir: Path = Path(".")


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


class _FakeChromaDBClient:
    def __init__(self) -> None:
        self.indexed: dict[str, list[dict[str, object]]] = {
            "LiteratureSentence": [],
            "LiteratureParagraph": [],
            "LiteratureDocument": [],
        }

    def ensure_literature_schema(self) -> None:
        return None

    def upsert(self, class_name: str, object_id: str, properties: dict[str, object], vector: list[float]) -> None:
        self.indexed[class_name].append(
            {"id": object_id, "properties": dict(properties), "vector": list(vector)}
        )

    def upsert_many(self, class_name: str, rows: list[tuple[str, dict[str, object], list[float]]]) -> None:
        for object_id, properties, vector in rows:
            self.upsert(class_name, object_id, properties, vector)

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
    def test_default_embedding_fallback_returns_non_empty_vectors_without_api_key(self) -> None:
        service = LiteratureService(settings=_FakeSettings(), generator_client=_FakeGenerator())

        vectors = service.embedding.embed_texts(["Supply chain resilience matters.", ""])

        self.assertEqual(len(vectors), 2)
        self.assertGreater(len(vectors[0]), 0)
        self.assertEqual(len(vectors[0]), len(vectors[1]))
        self.assertGreater(sum(abs(x) for x in vectors[1]), 0)

    def test_paper_key_for_long_title_is_bounded_for_windows_paths(self) -> None:
        service = LiteratureService(
            settings=_FakeSettings(),
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        title = "Self-regulation, corruption and competitiveness in extractive industries " * 6

        paper_key = service._paper_key_for_row({"title": title, "doi": ""}, source_path=None, html_text="")

        self.assertTrue(paper_key.startswith("title_"))
        self.assertLessEqual(len(paper_key), 48)

    def test_pdf_materialize_target_path_stays_under_windows_limit(self) -> None:
        service = LiteratureService(
            settings=_FakeSettings(),
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        title = "Self-regulation, corruption, and competitiveness in extractive industries: Making transparency pay"
        paper_key = service._paper_key_for_row({"title": title, "doi": "job::job_abc"}, source_path=None, html_text="")
        target_root = (
            Path(r"C:\Users\admin\AppData\Roaming\scholar-wiki\data\libraries\workspaces\ai washing")
            / "corpus"
            / "papers"
            / paper_key
            / "derived"
            / "mineru"
            / "latest"
            / "images"
            / "3dea82980b956e4637786d68313f2807b815f2e89605f6aa923b096d9c13247d.jpg"
        )

        self.assertLessEqual(len(str(target_root)), 240)

    def test_list_libraries_reads_workspaces_and_db_counts(self) -> None:
        service = LiteratureService(
            settings=_FakeSettings(),
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspaces = root / "libraries" / "workspaces"
            workspaces.mkdir(parents=True, exist_ok=True)

            (workspaces / ".agents").mkdir(parents=True, exist_ok=True)
            lib_a = workspaces / "smj"
            lib_a.mkdir(parents=True, exist_ok=True)
            lib_b = workspaces / "empty_lib"
            lib_b.mkdir(parents=True, exist_ok=True)

            import sqlite3

            db_path = lib_a / "kn_gragh.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("create table papers (paper_id text primary key)")
            cur.execute("insert into papers (paper_id) values ('p1')")
            cur.execute("insert into papers (paper_id) values ('p2')")
            conn.commit()
            conn.close()

            service._settings.workspaces_dir = workspaces  # type: ignore[assignment]
            service._settings.indexes_dir = str(root / "indexes")  # type: ignore[assignment]

            payload = service.list_libraries()
            libraries = payload.get("libraries", [])
            ids = sorted(str(x.get("library_id", "")) for x in libraries)
            self.assertEqual(ids, ["empty_lib", "smj"])
            by_id = {str(x.get("library_id", "")): x for x in libraries}
            self.assertEqual(int(by_id["smj"].get("paper_count", -1)), 2)
            self.assertEqual(int(by_id["empty_lib"].get("paper_count", -1)), 0)

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
        fake_chroma = _FakeChromaDBClient()
        fake_embed = _FakeEmbeddingClient()
        fake_gen = _FakeGenerator()
        service = LiteratureService(
            settings=_FakeSettings(),
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

            with patch.object(service, "_get_chroma", return_value=fake_chroma):
                import_result = service.import_manifest(manifest_path)

        self.assertEqual(import_result["imported_count"], 1)
        self.assertGreaterEqual(len(fake_chroma.indexed["LiteratureSentence"]), 1)

        with patch.object(service, "_get_chroma", return_value=fake_chroma):
            search_result = service.search(query="One", top_k=3, levels=["sentence"], library_id="lib_test", keyword_weight=0.4, rag_weight=0.6, include_expanded_context=True)
        self.assertIn("keyword_hits", search_result)
        self.assertIn("rag_hits", search_result)
        self.assertIn("merged_hits", search_result)
        self.assertGreaterEqual(len(search_result["merged_hits"]), 1)

        with patch.object(service, "_get_chroma", return_value=fake_chroma):
            answer_result = service.answer(query="What is this paper about?", top_k=2, levels=["sentence"], library_id="lib_test", keyword_weight=0.4, rag_weight=0.6)
        self.assertEqual(answer_result["answer"], "answer-from-llm")
        self.assertGreaterEqual(len(answer_result["citations"]), 1)

    def test_import_materializes_workspace_assets(self) -> None:
        fake_chroma = _FakeChromaDBClient()
        service = LiteratureService(
            settings=_FakeSettings(),
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
                service._settings.workspaces_dir = tmp / "workspaces"  # type: ignore[assignment]

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
                with patch.object(service, "_get_chroma", return_value=fake_chroma):
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
                sentence_props = fake_chroma.indexed["LiteratureSentence"][0]["properties"]
                self.assertIn("corpus", str(sentence_props.get("source_html", "")))
        finally:
            for key, value in old_env.items():
                if value:
                    os.environ[key] = value
                elif key in os.environ:
                    os.environ.pop(key, None)

    def test_import_pdf_uses_mineru_latest_folder(self) -> None:
        fake_chroma = _FakeChromaDBClient()
        service = LiteratureService(
            settings=_FakeSettings(),
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
                service._settings.workspaces_dir = tmp / "workspaces"  # type: ignore[assignment]

                pdf_path = tmp / "demo.pdf"
                pdf_path.write_bytes(b"%PDF-1.4 fake")
                preparsed_dir = tmp / "preparsed"
                preparsed_dir.mkdir(parents=True, exist_ok=True)
                preparsed_md = preparsed_dir / "parsed.md"
                preparsed_md.write_text("# PDF Demo\n\nBody", encoding="utf-8")
                preparsed_html = preparsed_dir / "parsed.html"
                preparsed_html.write_text("<html><body>PDF Parsed</body></html>", encoding="utf-8")
                manifest_path = tmp / "manifest.jsonl"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "paper_id": "paper_pdf",
                            "doi": "",
                            "title": "PDF Demo",
                            "source_path": str(pdf_path),
                            "preparsed_mineru_dir": str(preparsed_dir),
                            "preparsed_main_md_path": str(preparsed_md),
                            "preparsed_html_path": str(preparsed_html),
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                with patch.object(service, "_get_chroma", return_value=fake_chroma):
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
        fake_chroma = _FakeChromaDBClient()
        service = LiteratureService(
            settings=_FakeSettings(),
            embedding_client=_FakeEmbeddingClient(),
            generator_client=_FakeGenerator(),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            workspaces = tmp / "workspaces"
            (workspaces / "lib_pdf").mkdir(parents=True, exist_ok=True)
            service._settings.workspaces_dir = workspaces  # type: ignore[assignment]

            pdf_path = tmp / "a.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            preparsed_dir = tmp / "preparsed"
            preparsed_dir.mkdir(parents=True, exist_ok=True)
            preparsed_md = preparsed_dir / "random.md"
            preparsed_md.write_text("# My Great Paper\n\nBody", encoding="utf-8")
            preparsed_html = preparsed_dir / "parsed.html"
            preparsed_html.write_text("<html><body><pre># My Great Paper\n\nBody</pre></body></html>", encoding="utf-8")

            manifest_path = tmp / "manifest.jsonl"
            manifest_path.write_text(
                json.dumps(
                    {
                        "paper_id": "paper_pdf",
                        "title": "Fallback",
                        "source_path": str(pdf_path),
                        "preparsed_mineru_dir": str(preparsed_dir),
                        "preparsed_main_md_path": str(preparsed_md),
                        "preparsed_html_path": str(preparsed_html),
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(service, "_get_chroma", return_value=fake_chroma):
                result = service.import_manifest(manifest_path, options={"library_id": "lib_pdf"})
            mat = result["materialized_papers"][0]
            main_md = Path(str(mat["mineru_main_md_path"]))
            self.assertTrue(main_md.exists())
            self.assertEqual(main_md.name, "My Great Paper.md")

    def test_chromadb_client_persist_and_search(self) -> None:
        """Verify that ChromaDBClient persists data and supports keyword + vector search."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            client = ChromaDBClient(str(Path(tmp_dir) / "chromadb"))
            try:
                client.ensure_literature_schema()

                client.upsert(
                    "LiteratureSentence",
                    "sent-1",
                    {
                        "library_id": "lib_x",
                        "paper_id": "paper-a",
                        "title": "Test Paper",
                        "paragraph_id": "para-1",
                        "sentence_id": "sent-1",
                        "text": "Supply chain resilience is critical for firm performance.",
                        "position": 1,
                        "source_html": "/path/to/source.html",
                        "doi": "10.1000/test",
                    },
                    vector=[0.1, 0.2, 0.3],
                )

                kw_results = client.bm25_search("LiteratureSentence", query="supply chain", limit=5)
                self.assertGreaterEqual(len(kw_results), 1)
                self.assertEqual(kw_results[0]["properties"]["paper_id"], "paper-a")

                vec_results = client.vector_search("LiteratureSentence", vector=[0.1, 0.2, 0.3], limit=5)
                self.assertGreaterEqual(len(vec_results), 1)
                self.assertEqual(vec_results[0]["id"], "sent-1")
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
