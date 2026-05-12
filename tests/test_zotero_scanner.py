import unittest
import sqlite3
import tempfile
import os
from pathlib import Path


class TestZoteroScanner(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "zotero.sqlite")
        self.storage_dir = os.path.join(self.tmpdir, "storage")
        os.makedirs(self.storage_dir)
        self._create_fixture_db()

    def _create_fixture_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT NOT NULL, dateAdded TEXT, dateModified TEXT,
                libraryID INT NOT NULL DEFAULT 1, key TEXT NOT NULL, version INT DEFAULT 0, synced INT DEFAULT 0);
            CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT, PRIMARY KEY(itemID, fieldID));
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT UNIQUE);
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INT);
            CREATE TABLE itemCreators (itemID INT NOT NULL, creatorID INT NOT NULL, creatorTypeID INT NOT NULL DEFAULT 1,
                orderIndex INT NOT NULL DEFAULT 0, PRIMARY KEY(itemID, creatorID, creatorTypeID, orderIndex),
                UNIQUE(itemID, orderIndex));
            CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT, linkMode INT,
                contentType TEXT, path TEXT);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INT, note TEXT, title TEXT);
            CREATE TABLE itemAnnotations (itemID INTEGER PRIMARY KEY, parentItemID INT, type INT, authorName TEXT,
                text TEXT, comment TEXT, color TEXT, pageLabel TEXT, sortIndex TEXT, position TEXT, isExternal INT);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INT,
                libraryID INT, key TEXT);
            CREATE TABLE collectionItems (collectionID INT, itemID INT, orderIndex INT, PRIMARY KEY(collectionID, itemID));
            CREATE TABLE settings (setting TEXT, key TEXT, value TEXT, PRIMARY KEY(setting, key));
            CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY, dateDeleted TEXT DEFAULT CURRENT_TIMESTAMP);

            INSERT INTO itemTypes VALUES (1, 'journalArticle'), (2, 'attachment'), (3, 'note'), (4, 'annotation');
            INSERT INTO fields VALUES (1, 'title'), (2, 'date'), (3, 'publicationTitle'), (4, 'volume'), (5, 'issue'),
                (6, 'pages'), (7, 'DOI'), (8, 'abstractNote'), (9, 'url');
            INSERT INTO creatorTypes VALUES (1, 'author'), (2, 'editor');

            -- Paper item with PDF, note, annotation
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (1, 1, 1, 'ABC12345', '2025-01-01', '2025-01-01');
            INSERT INTO itemData VALUES (1, 1, 1), (1, 2, 2), (1, 3, 3), (1, 7, 4);
            INSERT INTO itemDataValues VALUES (1, 'A Test Paper Title'), (2, '2024'), (3, 'Journal of Testing'), (4, '10.1234/test.1');
            INSERT INTO creators VALUES (1, 'John', 'Smith', 0);
            INSERT INTO itemCreators VALUES (1, 1, 1, 0);

            -- PDF attachment
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (2, 2, 1, 'DEF67890', '2025-01-01', '2025-01-01');
            INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path)
                VALUES (2, 1, 1, 'application/pdf', 'storage:test.pdf');

            -- Note
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (3, 3, 1, 'GHI11111', '2025-01-01', '2025-01-01');
            INSERT INTO itemNotes VALUES (3, 1, 'An important research note', 'Note Title');

            -- Annotation
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (4, 4, 1, 'JKL22222', '2025-01-01', '2025-01-01');
            INSERT INTO itemAnnotations VALUES (4, 2, 1, 'John Smith',
                'This is the highlighted text', 'My comment on the highlight',
                '#ffd400', '45', '00044|003653|00262',
                '{"pageIndex":44,"rects":[[75.26,376.42,183.30,385.50]]}', 0);

            -- Collection
            INSERT INTO collections VALUES (1, 'Research Papers', NULL, 1, 'COL00001');
            INSERT INTO collectionItems VALUES (1, 1, 0);

            -- No-PDF item (should not appear)
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (5, 1, 1, 'NOPDF999', '2025-01-01', '2025-01-01');
        """)
        conn.commit()
        conn.close()

        # Create the storage file for the PDF attachment
        storage_item_dir = os.path.join(self.storage_dir, 'DEF67890')
        os.makedirs(storage_item_dir, exist_ok=True)
        Path(os.path.join(storage_item_dir, 'test.pdf')).touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scan_returns_items_with_pdf(self):
        from kn_graph.services.zotero_scanner import scan_zotero
        result = scan_zotero(self.tmpdir)
        self.assertEqual(result["total_count"], 1)
        # top-level collections list
        self.assertIn("collections", result)
        top_colls = result["collections"]
        self.assertEqual(len(top_colls), 1)
        self.assertEqual(top_colls[0]["name"], "Research Papers")
        item = result["items"][0]
        self.assertEqual(item["item_id"], 1)
        self.assertEqual(item["title"], "A Test Paper Title")
        self.assertEqual(item["date"], "2024")
        self.assertEqual(item["publication_title"], "Journal of Testing")
        self.assertEqual(item["doi"], "10.1234/test.1")
        self.assertEqual(item["item_type"], "journalArticle")
        self.assertEqual(item["key"], "ABC12345")
        self.assertEqual(len(item["creators"]), 1)
        self.assertEqual(item["creators"][0]["first_name"], "John")
        self.assertEqual(item["creators"][0]["last_name"], "Smith")
        self.assertEqual(len(item["pdf_paths"]), 1)
        self.assertTrue(item["pdf_paths"][0].endswith("test.pdf"))
        self.assertEqual(item["note_count"], 1)
        self.assertEqual(item["annotation_count"], 1)
        self.assertEqual(item["collections"], ["Research Papers"])

    def test_get_full_returns_complete_item(self):
        from kn_graph.services.zotero_scanner import get_zotero_item_full
        result = get_zotero_item_full(self.tmpdir, 1)
        self.assertIsNotNone(result)
        self.assertEqual(result["item_id"], 1)
        self.assertEqual(result["item_type"], "journalArticle")
        self.assertEqual(result["key"], "ABC12345")
        self.assertEqual(result["metadata"]["title"], "A Test Paper Title")
        self.assertEqual(result["metadata"]["DOI"], "10.1234/test.1")
        self.assertEqual(len(result["creators"]), 1)
        self.assertEqual(result["creators"][0]["first_name"], "John")
        self.assertEqual(result["creators"][0]["last_name"], "Smith")
        # PDF paths included regardless of existence in get_full
        self.assertEqual(len(result["pdf_paths"]), 1)
        self.assertEqual(result["pdf_paths"][0]["content_type"], "application/pdf")
        self.assertTrue(result["pdf_paths"][0]["file_exists"])
        # Notes with full content
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(result["notes"][0]["content"], "An important research note")
        # Annotations sorted by sortIndex
        self.assertEqual(len(result["annotations"]), 1)
        self.assertEqual(result["annotations"][0]["text"], "This is the highlighted text")
        self.assertEqual(result["annotations"][0]["comment"], "My comment on the highlight")
        self.assertEqual(result["annotations"][0]["page_label"], "45")
        self.assertEqual(result["annotations"][0]["sort_index"], "00044|003653|00262")
        # Collections
        self.assertEqual(result["collections"], ["Research Papers"])

    def test_get_full_returns_none_for_missing_item(self):
        from kn_graph.services.zotero_scanner import get_zotero_item_full
        result = get_zotero_item_full(self.tmpdir, 999)
        self.assertIsNone(result)
