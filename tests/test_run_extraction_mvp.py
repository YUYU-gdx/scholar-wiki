from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "run_extraction_mvp.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_run_extraction_mvp", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

run = _MOD.run
RunSummary = _MOD.RunSummary
RunArtifacts = _MOD.RunArtifacts


class _QualifierResult:
    def __init__(self, doc_class: str) -> None:
        self.doc_class = doc_class


def _empty_bundle():
    return _MOD._EXTRACTOR_MOD.ExtractionBundle(
        extractability_status="yes",
        paper_type="quantitative_empirical",
        extractability_reason="ok",
        extractability_evidence_section="Methods",
        variable_definitions=[],
        direct_effects=[],
        moderations=[],
        interactions=[],
        paper_domains=[],
    )


class RunExtractionMvpTest(unittest.TestCase):
    def test_run_collects_only_class_a_and_excludes_class_b_from_denominator(self) -> None:
        manifest_rows = [
            {"paper_id": "b-1", "html": "class-b"},
            {"paper_id": "a-1", "html": "class-a-1"},
            {"paper_id": "c-1", "html": "class-c"},
            {"paper_id": "b-2", "html": "class-b"},
            {"paper_id": "a-2", "html": "class-a-2"},
            {"paper_id": "a-3", "html": "class-a-3"},
        ]
        classifications = {
            "class-b": _QualifierResult("B"),
            "class-a-1": _QualifierResult("A"),
            "class-c": _QualifierResult("C"),
            "class-a-2": _QualifierResult("A"),
            "class-a-3": _QualifierResult("A"),
        }
        processed_ids: list[str] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.jsonl"
            manifest_path.write_text(
                "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in manifest_rows),
                encoding="utf-8",
            )

            with patch.object(
                _MOD,
                "classify_document",
                side_effect=lambda html: classifications[html],
            ), patch.object(
                _MOD,
                "_process_class_a_record",
                side_effect=lambda row, *_args: (
                    processed_ids.append(row["paper_id"]) or (_empty_bundle(), [], {"paper_id": row["paper_id"], "status": "ok", "raw_response": "{}"})
                ),
            ):
                artifacts = run(manifest_path, sample_size=2)
                summary = artifacts.summary

        self.assertEqual(processed_ids, ["a-1", "a-2"])
        self.assertEqual(
            summary,
            RunSummary(
                seen=5,
                class_a_used=2,
                class_b_skipped=2,
                class_c_skipped=1,
                denominator_used=3,
            ),
        )

    def test_run_reads_offline_html_path_and_executes_pipeline_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            html_path = tmp / "doc1.html"
            html_path.write_text("<section><h2>Results</h2><p>ok</p></section>", encoding="utf-8")
            manifest_path = tmp / "manifest.jsonl"
            manifest_path.write_text(
                json.dumps({"paper_id": "p1", "offline_html_path": str(html_path)}, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            class _FakeLLM:
                def complete(self, user_content: str, system_prompt: str | None = None) -> str:
                    _ = user_content, system_prompt
                    return json.dumps(
                        {
                            "extractability_status": "yes",
                            "paper_type": "quantitative_empirical",
                            "extractability_reason": "has regression",
                            "extractability_evidence_section": "Methods",
                            "variable_definitions": [],
                            "direct_effects": [
                                {
                                    "source": "A",
                                    "target": "B",
                                    "effect_form": "positive",
                                    "evidence_text": "Results text",
                                    "verification": "supported",
                                }
                            ],
                            "moderations": [],
                            "interactions": [],
                        },
                        ensure_ascii=True,
                    )

            class _Repo:
                def __init__(self) -> None:
                    self.called = 0
                    self.last_paper = ""

                def replace_paper_bundle(self, paper_id: str, payload: dict[str, object]) -> None:
                    self.called += 1
                    self.last_paper = paper_id
                    self.last_payload = payload

            class _GraphRepo:
                def __init__(self) -> None:
                    self.called = 0
                    self.last_paper = ""

                def project_bundle(self, paper_id: str, payload: dict[str, object]) -> None:
                    self.called += 1
                    self.last_paper = paper_id

            db_repo = _Repo()
            graph_repo = _GraphRepo()
            with patch.object(_MOD, "classify_document", return_value=_QualifierResult("A")):
                artifacts = run(
                    manifest_path,
                    sample_size=1,
                    llm_client=_FakeLLM(),
                    db_repo=db_repo,
                    neo4j_repo=graph_repo,
                    project_root=Path.cwd(),
                )

        self.assertIsInstance(artifacts, RunArtifacts)
        self.assertEqual(artifacts.summary.class_a_used, 1)
        self.assertEqual(db_repo.called, 1)
        self.assertEqual(db_repo.last_paper, "p1")
        self.assertIn("direct_effects", db_repo.last_payload)
        self.assertEqual(graph_repo.called, 1)


if __name__ == "__main__":
    unittest.main()


