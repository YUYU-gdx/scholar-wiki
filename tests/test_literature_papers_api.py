from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kn_graph.routers.literature import create_router
from kn_graph.services.literature_service import LiteratureService
from kn_graph.services.sqlite_repo import SqliteRepo


class LiteraturePapersApiTest(unittest.TestCase):
    def test_list_library_papers_reads_sqlite_and_reports_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "workspaces" / "lib_a"
            workspace.mkdir(parents=True)
            pdf = workspace / "paper.pdf"
            md = workspace / "paper.md"
            html = workspace / "paper.html"
            pdf.write_bytes(b"%PDF-1.4")
            md.write_text("# Paper", encoding="utf-8")
            html.write_text("<html></html>", encoding="utf-8")

            conn = sqlite3.connect(str(workspace / "kn_gragh.db"))
            repo = SqliteRepo(conn)
            repo.apply_schema()
            conn.execute(
                """
                INSERT INTO papers (
                    paper_id, doi, title, authors_json, journal, publication_date,
                    publication_year, source_pdf_path, source_md_path, offline_html_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "paper-1",
                    "10.1/demo",
                    "Demo Paper",
                    '[{"name":"Alice"}]',
                    "Demo Journal",
                    "2025-01-02",
                    2025,
                    str(pdf),
                    str(md),
                    str(html),
                ),
            )
            conn.execute(
                "INSERT INTO papers (paper_id, title) VALUES (?, ?)",
                ("paper-2", "No Files Paper"),
            )
            conn.commit()
            conn.close()

            settings = type("S", (), {"workspaces_dir": root / "workspaces", "indexes_dir": root / "indexes"})()
            service = LiteratureService(settings=settings)
            app = FastAPI()
            app.include_router(create_router(service))

            response = TestClient(app).get("/literature/libraries/lib_a/papers")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["library_id"], "lib_a")
        self.assertEqual(payload["paper_count"], 2)
        papers = {row["paper_id"]: row for row in payload["papers"]}
        self.assertTrue(papers["paper-1"]["files"]["pdf"])
        self.assertTrue(papers["paper-1"]["files"]["markdown"])
        self.assertTrue(papers["paper-1"]["files"]["html"])
        self.assertFalse(papers["paper-2"]["files"]["pdf"])
        self.assertEqual(papers["paper-1"]["authors_json"], [{"name": "Alice"}])

    def test_list_library_papers_handles_minimal_legacy_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "workspaces" / "legacy"
            workspace.mkdir(parents=True)
            conn = sqlite3.connect(str(workspace / "kn_gragh.db"))
            conn.execute("CREATE TABLE papers (paper_id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO papers (paper_id) VALUES (?)", ("legacy-paper",))
            conn.commit()
            conn.close()

            settings = type("S", (), {"workspaces_dir": root / "workspaces", "indexes_dir": root / "indexes"})()
            service = LiteratureService(settings=settings)

            payload = service.list_library_papers("legacy")

        self.assertEqual(payload["paper_count"], 1)
        self.assertEqual(payload["papers"][0]["paper_id"], "legacy-paper")


if __name__ == "__main__":
    unittest.main()
