from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
