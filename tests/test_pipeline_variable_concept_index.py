from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kn_graph.services import pipeline_runtime as runtime


class _Store:
    def __init__(self) -> None:
        self.row = {
            "job_id": "job-1",
            "status": "running",
            "stage": "extract_entities",
            "progress": 90,
            "requested_cancel": False,
            "last_event": "stage_done",
        }
        self.updates: list[dict[str, object]] = []

    def get_job(self, job_id: str) -> dict[str, object] | None:
        _ = job_id
        return dict(self.row)

    def update_job(self, job_id: str, updates: dict[str, object]) -> dict[str, object]:
        _ = job_id
        self.row.update(updates)
        self.updates.append(dict(updates))
        return dict(self.row)


def _prepare_run_dirs(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "runs" / "job-1" / "run"
    (run_dir / "extract").mkdir(parents=True, exist_ok=True)
    (run_dir / "extract" / "raw_llm_outputs.jsonl").write_text(
        json.dumps({"paper_id": "placeholder", "status": "ok", "raw_response": "{}"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    input_pdf = tmp_path / "in.pdf"
    input_pdf.write_bytes(b"%PDF-1.4")
    return run_dir, input_pdf


def _build_import_result(workspace_path: Path) -> dict[str, object]:
    return {
        "imported_count": 1,
        "workspace_path": str(workspace_path),
        "materialized_papers": [
            {
                "paper_key": "paper-1",
                "paper_id": "paper-1",
                "title": "Paper One",
                "source_pdf_path": str(workspace_path / "paper.pdf"),
                "md_library_path": str(workspace_path / "paper_md"),
                "html_path": str(workspace_path / "paper.html"),
            }
        ],
    }


def test_finalize_after_import_syncs_concept_index_after_sqlite_import(tmp_path: Path) -> None:
    run_dir, input_pdf = _prepare_run_dirs(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    import_result = _build_import_result(workspace)
    store = _Store()
    order: list[str] = []

    def _fake_import_sqlite(**kwargs) -> None:
        _ = kwargs
        order.append("sqlite_import")

    def _fake_build_graph(artifact, views_out: Path) -> None:
        _ = artifact
        views_out.write_text("{}", encoding="utf-8")

    fake_index_service = MagicMock()
    fake_index_service.upsert_paper_variable_concepts.side_effect = (
        lambda **kwargs: (order.append("concept_index"), {"upserted": 1})[1]
    )

    with (
        patch.object(runtime, "_import_sqlite_main_inline", side_effect=_fake_import_sqlite),
        patch.object(runtime, "_build_artifact_from_sqlite", return_value={"ok": True}),
        patch.object(runtime, "run_build_from_artifact", side_effect=_fake_build_graph),
        patch("kn_graph.services.variable_concept_index.VariableConceptIndexService", return_value=fake_index_service),
    ):
        result = runtime._run_finalize_after_import(
            job_id="job-1",
            input_pdf=input_pdf,
            parse_meta={"html_path": "x.html"},
            extract_result={"summary": {"seen": 1}},
            run_dir=run_dir,
            store=store,
            options={"purge_job_workspace": False, "retain_job_intermediates": True},
            import_result=import_result,
            workspace_path=str(workspace),
            library_id="lib-1",
            imported_count=1,
        )

    assert order.index("sqlite_import") < order.index("concept_index")
    assert isinstance(result["concept_index_result"], dict)
    assert result["concept_index_warning"] == ""
    assert store.row["status"] == "completed"


def test_finalize_concept_index_failure_sets_warning_without_blocking_completed(tmp_path: Path) -> None:
    run_dir, input_pdf = _prepare_run_dirs(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    store = _Store()
    import_result = _build_import_result(workspace)

    class _FakeLiteratureService:
        def __init__(self, settings) -> None:
            _ = settings

        def import_manifest(self, manifest_path: Path, options: dict[str, str]) -> dict[str, object]:
            _ = manifest_path, options
            return import_result

    def _fake_build_graph(artifact, views_out: Path) -> None:
        _ = artifact
        views_out.write_text("{}", encoding="utf-8")

    fake_index_service = MagicMock()
    fake_index_service.upsert_paper_variable_concepts.side_effect = RuntimeError("concept-sync-boom")

    with (
        patch("kn_graph.services.literature_service.LiteratureService", _FakeLiteratureService),
        patch.object(runtime, "_import_sqlite_main_inline", return_value=None),
        patch.object(runtime, "_build_artifact_from_sqlite", return_value={"ok": True}),
        patch.object(runtime, "run_build_from_artifact", side_effect=_fake_build_graph),
        patch("kn_graph.services.variable_concept_index.VariableConceptIndexService", return_value=fake_index_service),
    ):
        result = runtime._run_finalize(
            job_id="job-1",
            input_pdf=input_pdf,
            parse_meta={"html_path": "x.html"},
            extract_result={"summary": {"seen": 1}},
            run_dir=run_dir,
            store=store,
            options={"library_id": "lib-1", "_workspace_path": str(workspace), "purge_job_workspace": False, "retain_job_intermediates": True},
        )

    assert result["final_verdict"] == "success"
    assert isinstance(result["concept_index_result"], dict)
    assert "concept-sync-boom" in str(result["concept_index_warning"])
    assert store.row["status"] == "completed"
