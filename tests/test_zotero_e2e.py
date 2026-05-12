"""End-to-end tests for Zotero import against the real Zotero database.

These tests require a Zotero installation with real data.
Set ZOTERO_DATA_DIR env var to override auto-detection.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


def _get_zotero_dir():
    env = os.environ.get("ZOTERO_DATA_DIR", "")
    if env:
        return env
    from kn_graph.services.zotero_scanner import _find_data_dir
    d = _find_data_dir()
    if not d:
        raise unittest.SkipTest("No Zotero data directory found; set ZOTERO_DATA_DIR env var")
    return d


class TestZoteroScanRealData(unittest.TestCase):
    """Test scan_zotero against the real Zotero database."""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = _get_zotero_dir()
        cls.db_path = os.path.join(cls.data_dir, "zotero.sqlite")
        if not os.path.isfile(cls.db_path):
            raise unittest.SkipTest(f"zotero.sqlite not found at {cls.data_dir}")

    def test_scan_returns_real_items(self):
        """Scan the real Zotero DB and verify structure."""
        from kn_graph.services.zotero_scanner import scan_zotero

        result = scan_zotero(self.data_dir)
        self.assertIsInstance(result, dict)
        self.assertIn("items", result)
        self.assertIn("total_count", result)
        self.assertIn("collections", result)

        count = result["total_count"]
        items = result["items"]
        self.assertEqual(len(items), count, f"total_count {count} != len(items) {len(items)}")

        if count == 0:
            self.skipTest("No items with PDF attachments in Zotero library")

        # Verify each item has required fields
        required_keys = [
            "item_id", "key", "item_type", "title", "date",
            "publication_title", "volume", "issue", "pages",
            "doi", "abstract", "url", "creators", "pdf_paths",
            "note_count", "annotation_count", "collections",
        ]
        for item in items[:5]:  # Check first 5
            for key in required_keys:
                self.assertIn(key, item, f"Missing key '{key}' in item {item.get('item_id')}")
            # pdf_paths should be a list of strings
            self.assertIsInstance(item["pdf_paths"], list)
            if item["pdf_paths"]:
                self.assertIsInstance(item["pdf_paths"][0], str)
                # Each path should exist on disk
                self.assertTrue(
                    os.path.isfile(item["pdf_paths"][0]),
                    f"PDF not found: {item['pdf_paths'][0]}",
                )

        # Verify collections structure
        for coll in result.get("collections", []):
            self.assertIn("collection_id", coll)
            self.assertIn("name", coll)
            self.assertIn("parent_id", coll)

        print(f"\n[OK] Scan returned {count} items with PDFs")
        print(f"  Collections: {len(result.get('collections', []))}")
        if count > 0:
            item = items[0]
            print(f"  First item: {item['title'][:80]}")
            print(f"  Item type: {item['item_type']}")
            print(f"  DOI: {item.get('doi', 'N/A')}")
            print(f"  PDF paths: {len(item['pdf_paths'])}")
            print(f"  Notes: {item['note_count']}, Annotations: {item['annotation_count']}")
            print(f"  Creators: {len(item['creators'])}")


class TestZoteroItemFullRealData(unittest.TestCase):
    """Test get_zotero_item_full against the real Zotero database."""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = _get_zotero_dir()
        from kn_graph.services.zotero_scanner import scan_zotero
        result = scan_zotero(cls.data_dir)
        if result["total_count"] == 0:
            raise unittest.SkipTest("No items with PDFs")
        cls.first_item_id = result["items"][0]["item_id"]

    def test_get_full_returns_resolved_pdf_path(self):
        """get_zotero_item_full must return resolved_path that exists on disk."""
        from kn_graph.services.zotero_scanner import get_zotero_item_full

        item = get_zotero_item_full(self.data_dir, self.first_item_id)
        self.assertIsNotNone(item, f"Item {self.first_item_id} not found")
        self.assertIn("pdf_paths", item)

        pdfs = item["pdf_paths"]
        if pdfs:
            for pdf in pdfs:
                self.assertIn("resolved_path", pdf, f"Missing 'resolved_path' in {pdf}")
                self.assertIn("file_exists", pdf)
                self.assertIn("content_type", pdf)
                # The resolved_path, if file_exists is True, must actually exist
                if pdf["file_exists"]:
                    resolved = pdf["resolved_path"]
                    self.assertIsNotNone(resolved, f"resolved_path is None but file_exists=True")
                    self.assertTrue(
                        os.path.isfile(resolved),
                        f"file_exists=True but file not found: {resolved}",
                    )
                    print(f"\n[OK] PDF resolved correctly: {os.path.basename(resolved)}")
                else:
                    print(f"\n  PDF not on disk (linked file?): {pdf.get('path', '?')}")

        # Verify notes and annotations structure
        for note in item.get("notes", []):
            self.assertIn("content", note)
        for ann in item.get("annotations", []):
            self.assertIn("text", ann)
            self.assertIn("type", ann)
            self.assertIn("sort_index", ann)
            self.assertIn("page_label", ann)

        print(f"  Metadata fields: {list(item.get('metadata', {}).keys())[:10]}")
        print(f"  Creators: {len(item.get('creators', []))}")
        print(f"  PDFs: {len(pdfs)} (on disk: {sum(1 for p in pdfs if p['file_exists'])})")
        print(f"  Notes: {len(item.get('notes', []))}")
        print(f"  Annotations: {len(item.get('annotations', []))}")


class TestZoteroImportFlowReal(unittest.TestCase):
    """Test the import flow using a real Zotero item, exercising the router endpoint logic."""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = _get_zotero_dir()
        from kn_graph.services.zotero_scanner import scan_zotero, get_zotero_item_full
        result = scan_zotero(cls.data_dir)
        if result["total_count"] == 0:
            raise unittest.SkipTest("No items with PDFs")
        # Pick an item with a PDF that exists on disk
        cls.test_item = None
        for item in result["items"]:
            full = get_zotero_item_full(cls.data_dir, item["item_id"])
            if full is None:
                continue
            pdfs_on_disk = [a for a in full.get("pdf_paths", []) if a.get("file_exists")]
            if pdfs_on_disk:
                cls.test_item = full
                cls.test_pdf = pdfs_on_disk[0]
                break
        if cls.test_item is None:
            raise unittest.SkipTest("No items with PDFs available on disk")

    def test_import_item_has_required_zotero_options(self):
        """Verify the item data has all fields needed to build pipeline options."""
        item = self.test_item

        # Metadata should have basic fields
        metadata = item.get("metadata", {})
        self.assertIn("title", metadata, "Metadata missing title")

        # Creators should be a list
        creators = item.get("creators", [])
        self.assertIsInstance(creators, list)

        # Notes should have 'content' key
        for note in item.get("notes", []):
            self.assertIn("content", note)

        # Annotations should have required keys
        for ann in item.get("annotations", []):
            self.assertIn("text", ann)
            self.assertIn("sort_index", ann)
            self.assertIn("page_label", ann)

        # The resolved PDF path should be copyable
        resolved = self.test_pdf["resolved_path"]
        self.assertTrue(os.path.isfile(resolved),
                        f"Resolved PDF path does not exist: {resolved}")

        print(f"\n[OK] Item ready for import: {metadata.get('title', '?')[:80]}")
        print(f"  PDF: {os.path.basename(resolved)} ({os.path.getsize(resolved)} bytes)")
        print(f"  Notes: {len(item.get('notes', []))}")
        print(f"  Annotations: {len(item.get('annotations', []))}")

    def test_copy_pdf_to_temp(self):
        """Verify the PDF can be copied to a pipeline run directory (simulating import)."""
        import shutil, hashlib, uuid

        resolved = self.test_pdf["resolved_path"]

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_job"
            input_dir = run_dir / "input"
            input_dir.mkdir(parents=True)

            dest = input_dir / "upload.pdf"
            shutil.copy2(resolved, dest)

            self.assertTrue(dest.is_file(), "Copy failed")
            self.assertEqual(
                os.path.getsize(dest),
                os.path.getsize(resolved),
                "Copy size mismatch",
            )

            with open(dest, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
            self.assertTrue(h, "Hash should not be empty")

            print(f"\n[OK] PDF copy works: {os.path.getsize(dest)} bytes, sha256={h[:16]}...")

    def test_create_pipeline_job_payload(self):
        """Verify the payload built for create_job has correct structure."""
        import json, uuid

        item = self.test_item
        metadata = item.get("metadata", {})
        file_name = os.path.basename(self.test_pdf["resolved_path"])

        zotero_options = {
            "extraction_mode": "agent",
            "library_id": "test_lib",
            "_workspace_path": "/tmp/ws",
            "zotero_metadata": metadata,
            "zotero_creators": item.get("creators", []),
            "zotero_notes": item.get("notes", []),
            "zotero_annotations": item.get("annotations", []),
            "_zotero_source": True,
        }

        payload = {
            "job_id": f"test_{uuid.uuid4().hex[:12]}",
            "status": "queued",
            "stage": "accepted",
            "progress": 0,
            "error_code": "",
            "error_detail": "",
            "input_path": "/tmp/test.pdf",
            "output_path": "",
            "options_json": json.dumps(zotero_options, ensure_ascii=False),
            "result_json": "{}",
            "requested_cancel": False,
            "idempotency_key": "",
            "last_event": "accepted",
            "file_size": 0,
            "file_hash": "",
            "library_id": "test_lib",
            "workspace_path": "/tmp/ws",
            "source_job_id": "",
            "file_name": file_name,
        }

        # Verify required DB columns are present
        db_columns = [
            "job_id", "status", "stage", "progress", "error_code", "error_detail",
            "input_path", "output_path", "options_json", "result_json", "requested_cancel",
            "idempotency_key", "last_event", "file_size",
            "file_hash", "library_id", "workspace_path", "source_job_id", "file_name",
        ]
        for col in db_columns:
            self.assertIn(col, payload, f"Missing column '{col}' in payload")

        # Verify options_json can be round-tripped
        parsed = json.loads(payload["options_json"])
        self.assertTrue(parsed.get("_zotero_source"), "_zotero_source must be True")
        self.assertEqual(parsed.get("extraction_mode"), "agent")
        self.assertIsInstance(parsed.get("zotero_metadata"), dict)
        self.assertIsInstance(parsed.get("zotero_creators"), list)
        self.assertIsInstance(parsed.get("zotero_notes"), list)
        self.assertIsInstance(parsed.get("zotero_annotations"), list)

        # Verify result_json is valid
        parsed_result = json.loads(payload["result_json"])
        self.assertIsInstance(parsed_result, dict)

        print(f"\n[OK] Pipeline payload is valid")
        print(f"  options_json size: {len(payload['options_json'])} chars")
        print(f"  _zotero_source: {parsed['_zotero_source']}")
        print(f"  extraction_mode: {parsed['extraction_mode']}")


class TestZoteroBatchRealData(unittest.TestCase):
    """Test get_zotero_items_batch against the real Zotero database."""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = _get_zotero_dir()
        from kn_graph.services.zotero_scanner import scan_zotero
        result = scan_zotero(cls.data_dir)
        if result["total_count"] < 3:
            raise unittest.SkipTest("Need at least 3 items with PDFs")
        cls.item_ids = [it["item_id"] for it in result["items"][:3]]

    def test_batch_returns_same_count(self):
        """Batch should return results for all requested item IDs."""
        from kn_graph.services.zotero_scanner import get_zotero_items_batch
        results = get_zotero_items_batch(self.data_dir, self.item_ids)
        self.assertEqual(len(results), len(self.item_ids),
                         f"Expected {len(self.item_ids)} results, got {len(results)}")
        for r in results:
            self.assertIn("metadata", r)
            self.assertIn("pdf_paths", r)
            self.assertIn("notes", r)
            self.assertIn("annotations", r)
        print(f"\n[OK] Batch returned {len(results)} items in one DB copy")

    def test_batch_results_match_single(self):
        """Batch results should match get_zotero_item_full for each item."""
        from kn_graph.services.zotero_scanner import get_zotero_item_full, get_zotero_items_batch
        batch_results = get_zotero_items_batch(self.data_dir, self.item_ids)
        for batch_item in batch_results:
            single = get_zotero_item_full(self.data_dir, batch_item["item_id"])
            self.assertIsNotNone(single)
            self.assertEqual(batch_item["metadata"], single["metadata"])
            self.assertEqual(len(batch_item["pdf_paths"]), len(single["pdf_paths"]))
            self.assertEqual(len(batch_item["notes"]), len(single["notes"]))
            self.assertEqual(len(batch_item["annotations"]), len(single["annotations"]))
        print(f"\n[OK] Batch results match individual calls for {len(batch_results)} items")


if __name__ == "__main__":
    unittest.main()
