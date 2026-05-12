# Zotero Local Library Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "从 Zotero 导入" button to the literature import page that opens a modal to scan local Zotero databases, select items, and import them through the existing pipeline system with Zotero metadata taking priority.

**Architecture:** New backend scanner module reads zotero.sqlite in read-only mode. Two new API endpoints handle scan and import. Import creates pipeline jobs with Zotero metadata in options, reusing the existing pipeline execution flow. Frontend modal provides folder-tree + table + detail three-column layout.

**Tech Stack:** Python (sqlite3 stdlib), FastAPI, React + Tailwind CSS, TypeScript

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/kn_graph/services/zotero_scanner.py` | NEW - Read zotero.sqlite, build scan results and manifest rows |
| `src/kn_graph/models/literature.py` | MODIFY - Add Zotero request/response models |
| `src/kn_graph/routers/literature.py` | MODIFY - Add /zotero/scan and /zotero/import endpoints |
| `scholarai-workbench/src/types.ts` | MODIFY - Add ZoteroItemInfo, ZoteroScanResponse types |
| `scholarai-workbench/src/api.ts` | MODIFY - Add scanZotero, importZoteroItems functions |
| `scholarai-workbench/src/components/ZoteroImportModal.tsx` | NEW - Full modal component |
| `scholarai-workbench/src/components/PipelineView.tsx` | MODIFY - Add "从 Zotero 导入" button |

---

### Task 1: Backend - Zotero scanner module

**Files:**
- Create: `src/kn_graph/services/zotero_scanner.py`
- Test: `tests/test_zotero_scanner.py`

- [ ] **Step 1: Write test for scan_zotero with a minimal SQLite fixture**

```python
# tests/test_zotero_scanner.py
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
            CREATE TABLE itemTypeFields (itemTypeID INT, fieldID INT, hide INT, orderIndex INT, PRIMARY KEY(itemTypeID, fieldID));
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INT, filesEditable INT);

            INSERT INTO libraries VALUES (1, 'user', 1, 1);
            INSERT INTO itemTypes VALUES (1, 'journalArticle');
            INSERT INTO itemTypes VALUES (2, 'attachment');
            INSERT INTO itemTypes VALUES (3, 'note');
            INSERT INTO itemTypes VALUES (4, 'annotation');

            INSERT INTO fields VALUES (1, 'title'), (2, 'date'), (3, 'publicationTitle'), (4, 'volume'), (5, 'issue'),
                (6, 'pages'), (7, 'DOI'), (8, 'abstractNote'), (9, 'url'), (10, 'ISSN');

            INSERT INTO itemTypeFields VALUES (1,1,0,0), (1,2,0,1), (1,3,0,2), (1,4,0,3), (1,5,0,4),
                (1,6,0,5), (1,7,0,6), (1,8,0,7), (1,9,0,8), (1,10,0,9);

            INSERT INTO creatorTypes VALUES (1, 'author'), (2, 'editor');

            -- Paper item
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (1, 1, 1, 'ABC12345', '2025-01-01', '2025-01-01');
            INSERT INTO itemData VALUES (1, 1, 1), (1, 2, 2), (1, 3, 3), (1, 7, 4);
            INSERT INTO itemDataValues VALUES (1, 'A Test Paper Title'), (2, '2024'), (3, 'Journal of Testing'), (4, '10.1234/test.1');

            -- Author
            INSERT INTO creators VALUES (1, 'John', 'Smith', 0);
            INSERT INTO itemCreators VALUES (1, 1, 1, 0);

            -- PDF attachment
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (2, 2, 1, 'DEF67890', '2025-01-01', '2025-01-01');
            INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path)
                VALUES (2, 1, 1, 'application/pdf', 'storage:test.pdf');
            -- Create storage folder for the attachment
            os.makedirs(os.path.join(self.storage_dir, 'DEF67890'), exist_ok=True)
            Path(os.path.join(self.storage_dir, 'DEF67890', 'test.pdf')).touch()

            -- Note
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (3, 3, 1, 'GHI11111', '2025-01-01', '2025-01-01');
            INSERT INTO itemNotes VALUES (3, 1, 'An important research note', 'Note Title');

            -- Annotation on PDF
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (4, 4, 1, 'JKL22222', '2025-01-01', '2025-01-01');
            INSERT INTO itemAnnotations VALUES (4, 2, 1, 'John Smith',
                'This is the highlighted text', 'My comment on the highlight',
                '#ffd400', '45', '00044|003653|00262',
                '{"pageIndex":44,"rects":[[75.26,376.42,183.30,385.50]]}', 0);

            -- Collection
            INSERT INTO collections VALUES (1, 'Research Papers', NULL, 1, 'COL00001');
            INSERT INTO collectionItems VALUES (1, 1, 0);

            -- No PDF item (should not appear in results)
            INSERT INTO items (itemID, itemTypeID, libraryID, key, dateAdded, dateModified)
                VALUES (5, 1, 1, 'NOPDF999', '2025-01-01', '2025-01-01');
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scan_returns_items_with_pdf(self):
        from kn_graph.services.zotero_scanner import scan_zotero
        result = scan_zotero(self.tmpdir)
        self.assertEqual(result["total_count"], 1)  # Only item 1 has PDF
        item = result["items"][0]
        self.assertEqual(item["item_id"], 1)
        self.assertEqual(item["title"], "A Test Paper Title")
        self.assertEqual(item["date"], "2024")
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

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd D:/Code/kn_gragh && uv run python -m pytest tests/test_zotero_scanner.py -v
```

Expected: FAIL with "No module named 'kn_graph.services.zotero_scanner'"

- [ ] **Step 3: Implement scan_zotero in zotero_scanner.py**

```python
# src/kn_graph/services/zotero_scanner.py
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


def _find_data_dir() -> str | None:
    """Auto-detect Zotero data directory from prefs.js."""
    import re
    appdata = os.environ.get("APPDATA", os.path.expanduser("~/AppData/Roaming"))
    profiles_root = os.path.join(appdata, "Zotero", "Zotero", "Profiles")
    if not os.path.isdir(profiles_root):
        return None
    for name in os.listdir(profiles_root):
        prefs_path = os.path.join(profiles_root, name, "prefs.js")
        if not os.path.isfile(prefs_path):
            continue
        with open(prefs_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        use_match = re.search(r'extensions\.zotero\.useDataDir",\s*(true|false)', content)
        if use_match and use_match.group(1) == "true":
            dir_match = re.search(r'extensions\.zotero\.dataDir",\s*"([^"]+)"', content)
            if dir_match:
                path = dir_match.group(1).replace("\\\\", "\\")
                if os.path.isdir(path):
                    return path
        break
    default = os.path.expanduser("~/Zotero")
    if os.path.isdir(default):
        return default
    return None


def _safe_open_zotero_db(data_dir: str) -> tuple[sqlite3.Connection, str]:
    """Copy zotero.sqlite to a temp file and open read-only."""
    src = os.path.join(data_dir, "zotero.sqlite")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"zotero.sqlite not found at {src}")
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    shutil.copy2(src, tmp.name)
    conn = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
    return conn, tmp.name


def _cleanup_temp_db(tmp_path: str) -> None:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


def _resolve_attachment_path(path_col: str, item_key: str, data_dir: str, base_dir: str) -> str | None:
    """Resolve a Zotero attachment path to an absolute filesystem path."""
    if not path_col:
        return None
    if path_col.startswith("storage:"):
        rel = path_col[len("storage:"):]
        return os.path.join(data_dir, "storage", item_key, rel)
    if path_col.startswith("attachments:"):
        rel = path_col[len("attachments:"):]
        if base_dir:
            return os.path.join(base_dir, rel)
        return None
    # Absolute path (linked file)
    if os.path.isabs(path_col):
        return path_col
    return None


def scan_zotero(data_dir: str) -> dict[str, Any]:
    """Scan a local Zotero data directory and return all items with PDF attachments.

    Returns:
        dict with keys: items (list), total_count (int), collections (list)
    """
    data_dir = os.path.expanduser(data_dir)
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    conn, tmp_path = _safe_open_zotero_db(data_dir)
    try:
        # Read baseDir for linked attachments
        base_dir = ""
        cursor = conn.execute("SELECT key, value FROM settings WHERE setting = 'baseDir'")
        for row in cursor:
            if row[0] == "baseDir":
                base_dir = row[1] or ""
                break

        # Get all itemTypeID -> typeName mapping (filter to literature types)
        EXCLUDED_TYPES = {"attachment", "note", "annotation", "case", "hearing"}
        cursor = conn.execute("SELECT itemTypeID, typeName FROM itemTypes")
        item_type_map = {}
        for row in cursor:
            if row[1] not in EXCLUDED_TYPES:
                item_type_map[row[0]] = row[1]

        # Find all literature items that have PDF attachments
        cursor = conn.execute("""
            SELECT DISTINCT i.itemID, i.itemTypeID, i.key, i.dateAdded, i.dateModified
            FROM items i
            JOIN itemAttachments ia ON ia.parentItemID = i.itemID
            WHERE i.itemTypeID NOT IN (
                SELECT itemTypeID FROM itemTypes WHERE typeName IN ('attachment', 'note', 'annotation')
            )
            AND ia.contentType = 'application/pdf'
            AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
        """)
        item_rows = list(cursor)

        if not item_rows:
            return {"items": [], "total_count": 0, "collections": []}

        item_ids = [r[0] for r in item_rows]
        item_id_set = set(item_ids)

        # Load all field data for these items
        placeholders = ",".join("?" for _ in item_ids)
        cursor = conn.execute(
            f"SELECT idv.itemID, f.fieldName, idv2.value FROM itemData idv "
            f"JOIN fields f ON f.fieldID = idv.fieldID "
            f"JOIN itemDataValues idv2 ON idv2.valueID = idv.valueID "
            f"WHERE idv.itemID IN ({placeholders})",
            item_ids,
        )
        field_data: dict[int, dict[str, str]] = {iid: {} for iid in item_ids}
        for row in cursor:
            field_data[row[0]][row[1]] = row[2] or ""

        # Load creators
        cursor = conn.execute(
            f"SELECT ic.itemID, c.firstName, c.lastName, ct.creatorType "
            f"FROM itemCreators ic "
            f"JOIN creators c ON c.creatorID = ic.creatorID "
            f"JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID "
            f"WHERE ic.itemID IN ({placeholders}) "
            f"ORDER BY ic.orderIndex",
            item_ids,
        )
        creators_map: dict[int, list[dict]] = {iid: [] for iid in item_ids}
        for row in cursor:
            creators_map[row[0]].append({
                "first_name": row[1] or "",
                "last_name": row[2] or "",
                "creator_type": row[3] or "author",
            })

        # Load attachments (PDF only)
        cursor = conn.execute(
            f"SELECT ia.itemID, ia.parentItemID, ia.path, i.key "
            f"FROM itemAttachments ia "
            f"JOIN items i ON i.itemID = ia.itemID "
            f"WHERE ia.parentItemID IN ({placeholders}) "
            f"AND ia.contentType = 'application/pdf'",
            item_ids,
        )
        attach_map: dict[int, list[str]] = {iid: [] for iid in item_ids}
        for row in cursor:
            resolved = _resolve_attachment_path(row[2], row[3], data_dir, base_dir)
            if resolved and os.path.isfile(resolved):
                attach_map[row[1]].append(resolved)

        # Count notes
        cursor = conn.execute(
            f"SELECT parentItemID, COUNT(*) FROM itemNotes "
            f"WHERE parentItemID IN ({placeholders}) GROUP BY parentItemID",
            item_ids,
        )
        note_counts: dict[int, int] = {iid: 0 for iid in item_ids}
        for row in cursor:
            note_counts[row[0]] = row[1]

        # Count annotations (on all child PDFs)
        cursor = conn.execute(
            f"""SELECT ia.parentItemID, COUNT(*)
            FROM itemAnnotations an
            JOIN itemAttachments ia ON ia.itemID = an.parentItemID
            WHERE ia.parentItemID IN ({placeholders})
            GROUP BY ia.parentItemID""",
            item_ids,
        )
        anno_counts: dict[int, int] = {iid: 0 for iid in item_ids}
        for row in cursor:
            anno_counts[row[0]] = row[1]

        # Load collections
        cursor = conn.execute(
            f"SELECT ci.itemID, c.collectionName FROM collectionItems ci "
            f"JOIN collections c ON c.collectionID = ci.collectionID "
            f"WHERE ci.itemID IN ({placeholders})",
            item_ids,
        )
        coll_map: dict[int, list[str]] = {iid: [] for iid in item_ids}
        for row in cursor:
            coll_map[row[0]].append(row[1])

        # Build result items
        items = []
        for row in item_rows:
            iid = row[0]
            fdata = field_data.get(iid, {})
            pdf_paths = attach_map.get(iid, [])
            if not pdf_paths:
                continue  # skip if PDF file is missing on disk
            items.append({
                "item_id": iid,
                "key": row[2],
                "item_type": item_type_map.get(row[1], "document"),
                "title": fdata.get("title", ""),
                "date": fdata.get("date", ""),
                "publication_title": fdata.get("publicationTitle", ""),
                "volume": fdata.get("volume", ""),
                "issue": fdata.get("issue", ""),
                "pages": fdata.get("pages", ""),
                "doi": fdata.get("DOI", ""),
                "abstract": fdata.get("abstractNote", ""),
                "url": fdata.get("url", ""),
                "creators": creators_map.get(iid, []),
                "pdf_paths": pdf_paths,
                "note_count": note_counts.get(iid, 0),
                "annotation_count": anno_counts.get(iid, 0),
                "collections": coll_map.get(iid, []),
            })

        # Build collection tree
        cursor = conn.execute(
            "SELECT collectionID, collectionName, parentCollectionID FROM collections ORDER BY collectionName"
        )
        collections = []
        for row in cursor:
            collections.append({
                "collection_id": row[0],
                "name": row[1],
                "parent_id": row[2],
            })

        return {"items": items, "total_count": len(items), "collections": collections}

    finally:
        conn.close()
        _cleanup_temp_db(tmp_path)


def get_zotero_item_full(data_dir: str, item_id: int) -> dict[str, Any]:
    """Get full data for a single Zotero item including notes and annotation texts.

    Used during import to build the manifest row with Zotero metadata.
    """
    data_dir = os.path.expanduser(data_dir)
    conn, tmp_path = _safe_open_zotero_db(data_dir)
    try:
        # Base directory for linked attachments
        base_dir = ""
        cursor = conn.execute("SELECT key, value FROM settings WHERE setting = 'baseDir'")
        for row in cursor:
            if row[0] == "baseDir":
                base_dir = row[1] or ""
                break

        # Item base
        cursor = conn.execute(
            "SELECT i.itemID, i.itemTypeID, i.key, it.typeName FROM items i "
            "JOIN itemTypes it ON it.itemTypeID = i.itemTypeID WHERE i.itemID = ?",
            (item_id,),
        )
        item_row = cursor.fetchone()
        if not item_row:
            raise ValueError(f"Item {item_id} not found in Zotero database")
        item_key = item_row[2]
        item_type = item_row[3]

        # Fields
        cursor = conn.execute(
            "SELECT f.fieldName, idv2.value FROM itemData idv "
            "JOIN fields f ON f.fieldID = idv.fieldID "
            "JOIN itemDataValues idv2 ON idv2.valueID = idv.valueID "
            "WHERE idv.itemID = ?", (item_id,),
        )
        fields = {}
        for row in cursor:
            fields[row[0]] = row[1] or ""

        # Creators
        cursor = conn.execute(
            "SELECT c.firstName, c.lastName, ct.creatorType FROM itemCreators ic "
            "JOIN creators c ON c.creatorID = ic.creatorID "
            "JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID "
            "WHERE ic.itemID = ? ORDER BY ic.orderIndex", (item_id,),
        )
        creators = []
        for row in cursor:
            creators.append({"first_name": row[0] or "", "last_name": row[1] or "", "creator_type": row[2] or "author"})

        # Attachments (PDF only)
        cursor = conn.execute(
            "SELECT ia.itemID, ia.path, i.key FROM itemAttachments ia "
            "JOIN items i ON i.itemID = ia.itemID "
            "WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'", (item_id,),
        )
        attachments = []
        for row in cursor:
            resolved = _resolve_attachment_path(row[1], row[2], data_dir, base_dir)
            if resolved:
                attachments.append({"item_id": row[0], "path": resolved})

        # Notes
        cursor = conn.execute(
            "SELECT itemID, note, title FROM itemNotes WHERE parentItemID = ?", (item_id,),
        )
        notes = []
        for row in cursor:
            notes.append({"item_id": row[0], "note": row[1] or "", "title": row[2] or ""})

        # Annotations on child PDFs
        anno_sql = """
            SELECT an.itemID, an.type, an.text, an.comment, an.color, an.pageLabel, an.sortIndex
            FROM itemAnnotations an
            JOIN items i ON i.itemID = an.parentItemID
            WHERE i.parentItemID = ?
            ORDER BY an.sortIndex
        """
        cursor = conn.execute(anno_sql, (item_id,))
        annotations = []
        for row in cursor:
            annotations.append({
                "item_id": row[0],
                "type": row[1],
                "text": row[2] or "",
                "comment": row[3] or "",
                "color": row[4] or "",
                "page_label": row[5] or "",
                "sort_index": row[6] or "",
            })

        return {
            "item_id": item_id,
            "key": item_key,
            "item_type": item_type,
            "fields": fields,
            "creators": creators,
            "attachments": attachments,
            "notes": notes,
            "annotations": annotations,
        }

    finally:
        conn.close()
        _cleanup_temp_db(tmp_path)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd D:/Code/kn_gragh && uv run python -m pytest tests/test_zotero_scanner.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd D:/Code/kn_gragh && git add src/kn_graph/services/zotero_scanner.py tests/test_zotero_scanner.py && git commit -m "feat: add Zotero scanner module for reading local zotero.sqlite"
```

---

### Task 2: Backend - Pydantic models for Zotero

**Files:**
- Modify: `src/kn_graph/models/literature.py`

- [ ] **Step 1: Add Zotero models to models/literature.py**

```python
# Append to the end of src/kn_graph/models/literature.py (after LiteratureSearchResponse)


class ZoteroScanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data_dir: str = ""


class ZoteroCreatorInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    first_name: str = ""
    last_name: str = ""
    creator_type: str = "author"


class ZoteroItemInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    item_id: int = 0
    key: str = ""
    item_type: str = ""
    title: str = ""
    date: str = ""
    publication_title: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    abstract: str = ""
    url: str = ""
    creators: list[dict[str, str]] = []
    pdf_paths: list[str] = []
    note_count: int = 0
    annotation_count: int = 0
    collections: list[str] = []


class ZoteroScanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[dict[str, Any]] = []
    total_count: int = 0
    collections: list[dict[str, Any]] = []


class ZoteroImportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data_dir: str = ""
    item_ids: list[int] = []
    library_id: str = ""


class ZoteroImportResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_ids: list[str] = []
    count: int = 0
```

- [ ] **Step 2: Verify models import correctly**

```bash
cd D:/Code/kn_gragh && uv run python -c "from kn_graph.models.literature import ZoteroScanRequest, ZoteroScanResponse, ZoteroImportRequest, ZoteroImportResponse, ZoteroItemInfo; print('OK')"
```

Expected: OK

- [ ] **Step 3: Commit**

```bash
cd D:/Code/kn_gragh && git add src/kn_graph/models/literature.py && git commit -m "feat: add Zotero Pydantic models for scan/import API"
```

---

### Task 3: Backend - API endpoints

**Files:**
- Modify: `src/kn_graph/routers/literature.py`

- [ ] **Step 1: Add Zotero endpoints to the literature router**

In `src/kn_graph/routers/literature.py`, add the import at the top and the two endpoints inside `create_router()`:

```python
# Add to imports at top:
from kn_graph.models.literature import (
    LiteratureAnswerRequest, LiteratureCreateLibraryRequest, LiteratureImportRequest,
    ZoteroScanRequest, ZoteroImportRequest,
)

# Add inside create_router(), after the /answer endpoint and before "return router":

    @router.post("/zotero/scan")
    async def zotero_scan(body: ZoteroScanRequest):
        data_dir = str(body.data_dir or "").strip()
        if not data_dir:
            from kn_graph.services.zotero_scanner import _find_data_dir
            data_dir = _find_data_dir() or ""
        if not data_dir:
            return JSONResponse(status_code=400, content={"error": "data_dir_required", "hint": "Please provide the Zotero data directory path"})
        try:
            from kn_graph.services.zotero_scanner import scan_zotero
            result = scan_zotero(data_dir)
            return result
        except FileNotFoundError as exc:
            return JSONResponse(status_code=400, content={"error": "zotero_db_not_found", "detail": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "zotero_scan_failed", "detail": str(exc)})

    @router.post("/zotero/import")
    async def zotero_import(body: ZoteroImportRequest):
        from kn_graph.services.zotero_scanner import get_zotero_item_full
        import uuid, json, shutil

        data_dir = str(body.data_dir or "").strip()
        library_id = str(body.library_id or "").strip()
        item_ids = list(body.item_ids)

        if not data_dir:
            return JSONResponse(status_code=400, content={"error": "data_dir_required"})
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        if not item_ids:
            return JSONResponse(status_code=400, content={"error": "item_ids_required"})

        ...  # the endpoint body continues below

- [ ] **Step 1: Modify create_router function signature and add Zotero endpoints**

In `src/kn_graph/routers/literature.py`:

```python
# In create_router function signature:
def create_router(literature_service: LiteratureService, pipeline_service: Any = None) -> APIRouter:

    # ... existing endpoints ...

    @router.post("/zotero/scan")
    async def zotero_scan(body: ZoteroScanRequest):
        data_dir = str(body.data_dir or "").strip()
        if not data_dir:
            from kn_graph.services.zotero_scanner import _find_data_dir
            data_dir = _find_data_dir() or ""
        if not data_dir:
            return JSONResponse(status_code=400, content={"error": "data_dir_required"})
        try:
            from kn_graph.services.zotero_scanner import scan_zotero
            result = scan_zotero(data_dir)
            return result
        except FileNotFoundError as exc:
            return JSONResponse(status_code=400, content={"error": "zotero_db_not_found", "detail": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "zotero_scan_failed", "detail": str(exc)})

    @router.post("/zotero/import")
    async def zotero_import(body: ZoteroImportRequest):
        import uuid, shutil, os
        from pathlib import Path
        from kn_graph.services.zotero_scanner import get_zotero_item_full
        from kn_graph.services.pipeline_runtime import dispatch_inline

        data_dir = str(body.data_dir or "").strip()
        library_id = str(body.library_id or "").strip()
        item_ids = list(body.item_ids)

        if not data_dir:
            return JSONResponse(status_code=400, content={"error": "data_dir_required"})
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        if not item_ids:
            return JSONResponse(status_code=400, content={"error": "item_ids_required"})
        if pipeline_service is None:
            return JSONResponse(status_code=500, content={"error": "pipeline_service_unavailable"})

        # Resolve workspace
        workspaces_dir = Path(literature_service._settings.workspaces_dir)
        workspace_path = workspaces_dir / library_id
        if not workspace_path.is_dir():
            return JSONResponse(status_code=400, content={"error": "workspace_not_found", "library_id": library_id})

        runs_root = Path(literature_service._settings.pipeline_runs_root)

        job_ids = []
        for item_id in item_ids:
            try:
                zotero_data = get_zotero_item_full(data_dir, item_id)
            except Exception as exc:
                continue

            pdf_paths = [a["path"] for a in zotero_data["attachments"]]
            if not pdf_paths:
                continue

            job_id = f"job_{uuid.uuid4().hex}"
            run_dir = runs_root / job_id
            input_dir = run_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)

            # Copy first PDF to input dir
            src_pdf = pdf_paths[0]
            dest_pdf = input_dir / "upload.pdf"
            shutil.copy2(src_pdf, dest_pdf)

            import hashlib
            file_size = os.path.getsize(dest_pdf)
            with open(dest_pdf, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()

            # Build zotero options
            zotero_options = {
                "extraction_mode": "agent",
                "zotero_metadata": zotero_data["fields"],
                "zotero_creators": zotero_data["creators"],
                "zotero_notes": zotero_data["notes"],
                "zotero_annotations": zotero_data["annotations"],
                "_zotero_source": True,
            }

            payload = {
                "job_id": job_id,
                "status": "queued",
                "stage": "accepted",
                "progress": 0,
                "error_code": "",
                "error_detail": "",
                "input_path": str(dest_pdf),
                "output_path": "",
                "options": zotero_options,
                "result": {},
                "requested_cancel": False,
                "idempotency_key": "",
                "last_event": "accepted",
                "file_size": file_size,
                "file_hash": file_hash,
                "library_id": library_id,
                "workspace_path": str(workspace_path),
                "source_job_id": "",
                "file_name": os.path.basename(src_pdf),
                "display_name": zotero_data["fields"].get("title", "") or os.path.basename(src_pdf),
            }
            pipeline_service.create_job(payload)

            # Dispatch inline execution
            dispatch_inline(pipeline_service._store, job_id, str(dest_pdf), zotero_options, runs_root)

            job_ids.append(job_id)

        return {"job_ids": job_ids, "count": len(job_ids)}
```

- [ ] **Step 2: Update app.py to pass pipeline_service to literature router**

In `src/kn_graph/app.py`, find the line:
```python
app.include_router(literature.create_router(literature_service))
```
Change to:
```python
app.include_router(literature.create_router(literature_service, pipeline_service))
```

- [ ] **Step 3: Write test for the scan endpoint**

```python
# tests/test_zotero_api.py
import unittest
import tempfile
import os
import json

class TestZoteroAPI(unittest.TestCase):
    def setUp(self):
        # Use the same fixture setup as test_zotero_scanner.py
        ...
```

(Skip detailed API test for now — integration test will cover this. Manual verification via curl is sufficient for initial implementation.)

- [ ] **Step 4: Verify endpoints with manual curl test**

```bash
# Start the server first, then test:
curl -X POST http://localhost:8013/literature/zotero/scan \
  -H "Content-Type: application/json" \
  -d '{"data_dir": "C:/Users/xxx/Zotero"}'
```

- [ ] **Step 5: Commit**

```bash
cd D:/Code/kn_gragh && git add src/kn_graph/routers/literature.py src/kn_graph/app.py && git commit -m "feat: add /zotero/scan and /zotero/import API endpoints"
```

---

### Task 4: Pipeline runtime — Inject Zotero annotations into markdown after Mineru parse

**Files:**
- Modify: `src/kn_graph/services/pipeline_runtime.py`

- [ ] **Step 1: Add helper to build Zotero markdown appendix**

Add this function to `pipeline_runtime.py`:

```python
def _build_zotero_appendix(options: dict) -> str:
    """Build a markdown appendix with Zotero notes and annotations."""
    notes = options.get("zotero_notes", []) or []
    annotations = options.get("zotero_annotations", []) or []
    parts: list[str] = []
    if notes:
        parts.append("## Zotero Notes\n")
        for n in notes:
            title = n.get("title", "")
            note_text = n.get("note", "")
            if title:
                parts.append(f"### {title}\n")
            parts.append(f"> {note_text}\n")
    if annotations:
        parts.append("## Zotero Annotations\n")
        # Group by page_label
        by_page: dict[str, list[dict]] = {}
        for ann in annotations:
            page = ann.get("page_label", "Unknown")
            by_page.setdefault(page, []).append(ann)
        for page in sorted(by_page.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            parts.append(f"### Page {page}\n")
            for ann in by_page[page]:
                text = ann.get("text", "")
                comment = ann.get("comment", "")
                color = ann.get("color", "")
                if text:
                    parts.append(f"> {text}  (highlight, {color})\n")
                if comment:
                    parts.append(f"Comment: {comment}\n")
                if text or comment:
                    parts.append("")
    return "\n".join(parts)
```

- [ ] **Step 2: Inject Zotero appendix after Mineru parse**

In `pipeline_runtime.py`, find the `_run_parse_pdf` function (or the parse_pdf stage). After Mineru produces the markdown file, check if `options["_zotero_source"]` is true, and if so, append the Zotero appendix.

Find the path where the Mineru main .md file is saved. After that save:
```python
# In _run_parse_pdf, after Mineru produces the main_md_path:
if options.get("_zotero_source"):
    appendix = _build_zotero_appendix(options)
    if appendix:
        with open(main_md_path, "a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(appendix)
        # Also update parse_meta.json
        meta_path = os.path.join(parse_dir, "parse_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["zotero_appendix_added"] = True
            meta["zotero_note_count"] = len(options.get("zotero_notes", []) or [])
            meta["zotero_annotation_count"] = len(options.get("zotero_annotations", []) or [])
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 3: Modify extraction stage to accept pre-filled Zotero metadata**

In the extraction stage (`_run_extract_entities` or `_run_agent_extraction`), after extraction completes, check for Zotero metadata and merge:

```python
def _merge_zotero_metadata(extract_result: dict, options: dict) -> dict:
    """Fill extraction result with Zotero metadata where extraction fields are empty."""
    zotero_fields = options.get("zotero_metadata", {}) or {}
    zotero_creators = options.get("zotero_creators", []) or []
    if not zotero_fields and not zotero_creators:
        return extract_result

    # Paper-level fields: Zotero wins if extraction is empty
    record = extract_result.get("record", {}) or {}
    paper = record.get("paper", {}) or {}

    FIELD_MAP = {
        "title": "title",
        "doi": "DOI",
        "abstract": "abstractNote",
        "publication_title": "publicationTitle",
        "year": "date",
        "volume": "volume",
        "issue": "issue",
        "pages": "pages",
        "url": "url",
    }
    for extract_key, zotero_key in FIELD_MAP.items():
        existing = paper.get(extract_key, "")
        if not existing and zotero_fields.get(zotero_key):
            paper[extract_key] = zotero_fields[zotero_key]

    # Authors: Zotero wins if extraction has no authors
    existing_authors = paper.get("authors", []) or []
    if not existing_authors and zotero_creators:
        paper["authors"] = [
            f"{c['last_name']}, {c['first_name']}" if c.get("last_name") else c.get("first_name", "")
            for c in zotero_creators
        ]

    record["paper"] = paper
    extract_result["record"] = record
    return extract_result
```

Call this after extraction completes but before the result is written.

- [ ] **Step 4: Commit**

```bash
cd D:/Code/kn_gragh && git add src/kn_graph/services/pipeline_runtime.py && git commit -m "feat: inject Zotero notes/annotations into markdown, merge Zotero metadata into extraction"
```

---

### Task 5: Frontend — TypeScript types

**Files:**
- Modify: `scholarai-workbench/src/types.ts`

- [ ] **Step 1: Add Zotero types**

Append to `scholarai-workbench/src/types.ts`:

```typescript
export interface ZoteroCreatorInfo {
  first_name: string;
  last_name: string;
  creator_type: string;
}

export interface ZoteroItemInfo {
  item_id: number;
  key: string;
  item_type: string;
  title: string;
  date: string;
  publication_title: string;
  volume: string;
  issue: string;
  pages: string;
  doi: string;
  abstract: string;
  url: string;
  creators: ZoteroCreatorInfo[];
  pdf_paths: string[];
  note_count: number;
  annotation_count: number;
  collections: string[];
}

export interface ZoteroScanResponse {
  items: ZoteroItemInfo[];
  total_count: number;
  collections: ZoteroCollectionInfo[];
}

export interface ZoteroCollectionInfo {
  collection_id: number;
  name: string;
  parent_id: number | null;
}

export interface ZoteroImportResponse {
  job_ids: string[];
  count: number;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd D:/Code/kn_gragh/scholarai-workbench && npx tsc --noEmit
```

Expected: No errors related to types

- [ ] **Step 3: Commit**

```bash
cd D:/Code/kn_gragh && git add scholarai-workbench/src/types.ts && git commit -m "feat: add Zotero TypeScript types"
```

---

### Task 6: Frontend — API functions

**Files:**
- Modify: `scholarai-workbench/src/api.ts`

- [ ] **Step 1: Add Zotero API functions**

In `scholarai-workbench/src/api.ts`, add a `zotero` namespace after the `literature:` namespace. Import types at top:

```typescript
// Add to imports at top (extend the existing import from './types'):
import type {
  // ... existing imports ...
  ZoteroScanResponse,
  ZoteroImportResponse,
} from './types';
```

Add the `zotero` namespace before the final `}` of the api object:

```typescript
  // After literature namespace, before the closing:
  zotero: {
    scan(dataDir: string): Promise<ZoteroScanResponse> {
      return jsonFetch('/literature/zotero/scan', {
        method: 'POST',
        body: JSON.stringify({ data_dir: dataDir }),
      });
    },
    importItems(dataDir: string, itemIds: number[], libraryId: string): Promise<ZoteroImportResponse> {
      return jsonFetch('/literature/zotero/import', {
        method: 'POST',
        body: JSON.stringify({ data_dir: dataDir, item_ids: itemIds, library_id: libraryId }),
      });
    },
  },
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd D:/Code/kn_gragh/scholarai-workbench && npx tsc --noEmit
```

Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd D:/Code/kn_gragh && git add scholarai-workbench/src/api.ts && git commit -m "feat: add Zotero API functions to frontend"
```

---

### Task 7: Frontend — ZoteroImportModal component

**Files:**
- Create: `scholarai-workbench/src/components/ZoteroImportModal.tsx`

- [ ] **Step 1: Create the ZoteroImportModal component**

```tsx
import { useState, useEffect, useMemo } from 'react';
import { Search, FileText, StickyNote, Highlighter, FolderTree, X, Database } from 'lucide-react';
import { useApp } from '../app-context';
import { api } from '../api';
import type { ZoteroItemInfo, ZoteroScanResponse, ZoteroCollectionInfo } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ZoteroImportModal({ open, onClose }: Props) {
  const { activeLibraryId, libraries } = useApp();
  const [dataDir, setDataDir] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ZoteroScanResponse | null>(null);
  const [scanError, setScanError] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedCollection, setSelectedCollection] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [previewItem, setPreviewItem] = useState<ZoteroItemInfo | null>(null);
  const [targetLibrary, setTargetLibrary] = useState(activeLibraryId);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState('');

  useEffect(() => {
    if (open) {
      setScanResult(null);
      setScanError('');
      setSelectedIds(new Set());
      setPreviewItem(null);
      setImportResult('');
      setTargetLibrary(activeLibraryId);
    }
  }, [open, activeLibraryId]);

  const handleScan = async () => {
    setScanning(true);
    setScanError('');
    setScanResult(null);
    try {
      const result = await api.zotero.scan(dataDir);
      setScanResult(result);
    } catch (e: unknown) {
      setScanError(e instanceof Error ? e.message : '扫描失败');
    } finally {
      setScanning(false);
    }
  };

  // Filter items by collection and search
  const filteredItems = useMemo(() => {
    if (!scanResult) return [];
    let items = scanResult.items;
    if (selectedCollection !== null) {
      const collName = scanResult.collections.find(c => c.collection_id === selectedCollection)?.name;
      if (collName) {
        items = items.filter(it => it.collections.includes(collName));
      }
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      items = items.filter(it =>
        it.title.toLowerCase().includes(q) ||
        it.creators.some(c =>
          `${c.last_name} ${c.first_name}`.toLowerCase().includes(q)
        )
      );
    }
    return items;
  }, [scanResult, selectedCollection, searchQuery]);

  const toggleSelect = (itemId: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === filteredItems.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredItems.map(it => it.item_id)));
    }
  };

  const handleImport = async () => {
    if (selectedIds.size === 0) return;
    setImporting(true);
    setImportResult('');
    try {
      const result = await api.zotero.importItems(dataDir, [...selectedIds], targetLibrary);
      setImportResult(`${result.count} 个任务已提交，关闭弹窗后可在任务列表中查看进度`);
      setSelectedIds(new Set());
    } catch (e: unknown) {
      setImportResult(`导入失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setImporting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-surface-container-lowest border border-outline-variant rounded-2xl shadow-2xl w-[95vw] max-w-[1400px] h-[85vh] flex flex-col mx-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant shrink-0">
          <h2 className="text-lg font-bold text-on-surface">从 Zotero 导入</h2>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-container transition-colors">
            <X className="w-5 h-5 text-on-surface-variant" />
          </button>
        </div>

        {/* Top bar — data dir + scan */}
        <div className="px-6 py-3 border-b border-outline-variant flex items-center gap-3 shrink-0">
          <Database className="w-4 h-4 text-outline shrink-0" />
          <input
            type="text"
            value={dataDir}
            onChange={e => setDataDir(e.target.value)}
            placeholder="Zotero 数据目录 (留空自动检测)"
            className="flex-1 bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-sm text-on-surface placeholder:text-outline focus:outline-none focus:border-secondary"
          />
          <button
            onClick={handleScan}
            disabled={scanning}
            className="bg-secondary text-on-secondary px-4 py-2 rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50 shrink-0"
          >
            {scanning ? '扫描中...' : '扫描'}
          </button>
        </div>

        {/* Error */}
        {scanError && (
          <div className="mx-6 mt-3 px-4 py-2 bg-error-container text-error rounded-lg text-sm">{scanError}</div>
        )}

        {/* Import result */}
        {importResult && (
          <div className="mx-6 mt-3 px-4 py-2 bg-tertiary-container text-on-tertiary-container rounded-lg text-sm">{importResult}</div>
        )}

        {/* Main content */}
        <div className="flex-1 flex min-h-0">
          {/* Left — Collections */}
          <div className="w-56 border-r border-outline-variant overflow-y-auto shrink-0 p-3">
            <div className="flex items-center gap-2 mb-2 text-xs font-bold text-on-surface uppercase tracking-wider">
              <FolderTree className="w-3.5 h-3.5" />
              文件夹
            </div>
            <button
              onClick={() => setSelectedCollection(null)}
              className={`w-full text-left px-2 py-1.5 rounded text-sm mb-1 ${
                selectedCollection === null ? 'bg-secondary-container text-on-secondary-container font-medium' : 'text-on-surface-variant hover:bg-surface-container'
              }`}
            >
              全部 ({scanResult?.total_count ?? 0})
            </button>
            {scanResult?.collections.map(coll => (
              <button
                key={coll.collection_id}
                onClick={() => setSelectedCollection(coll.collection_id)}
                className={`w-full text-left px-2 py-1.5 rounded text-sm truncate ${
                  selectedCollection === coll.collection_id ? 'bg-secondary-container text-on-secondary-container font-medium' : 'text-on-surface-variant hover:bg-surface-container'
                }`}
                title={coll.name}
              >
                {coll.name}
              </button>
            ))}
          </div>

          {/* Center — Item table */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="px-4 py-2 border-b border-outline-variant flex items-center gap-2 shrink-0">
              <Search className="w-3.5 h-3.5 text-outline shrink-0" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="搜索标题或作者..."
                className="flex-1 bg-transparent text-sm text-on-surface placeholder:text-outline focus:outline-none"
              />
              <span className="text-xs text-outline font-mono shrink-0">
                已选 {selectedIds.size}/{filteredItems.length}
              </span>
            </div>
            <div className="flex-1 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-container-lowest">
                  <tr className="border-b border-outline-variant">
                    <th className="w-10 px-3 py-2">
                      <input type="checkbox" checked={selectedIds.size === filteredItems.length && filteredItems.length > 0} onChange={toggleAll} />
                    </th>
                    <th className="text-left px-2 py-2 text-xs font-bold text-on-surface uppercase tracking-wider">标题</th>
                    <th className="text-left px-2 py-2 text-xs font-bold text-on-surface uppercase tracking-wider w-28">作者</th>
                    <th className="text-left px-2 py-2 text-xs font-bold text-on-surface uppercase tracking-wider w-16">年份</th>
                    <th className="text-center px-2 py-2 text-xs font-bold text-on-surface uppercase tracking-wider w-10" title="PDF"><FileText className="w-3.5 h-3.5 inline" /></th>
                    <th className="text-center px-2 py-2 text-xs font-bold text-on-surface uppercase tracking-wider w-10" title="笔记"><StickyNote className="w-3.5 h-3.5 inline" /></th>
                    <th className="text-center px-2 py-2 text-xs font-bold text-on-surface uppercase tracking-wider w-10" title="标注"><Highlighter className="w-3.5 h-3.5 inline" /></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map(item => (
                    <tr
                      key={item.item_id}
                      className={`border-b border-outline-variant/50 cursor-pointer hover:bg-surface-container transition-colors ${
                        previewItem?.item_id === item.item_id ? 'bg-secondary-container/20' : ''
                      }`}
                      onClick={() => setPreviewItem(item)}
                    >
                      <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                        <input type="checkbox" checked={selectedIds.has(item.item_id)} onChange={() => toggleSelect(item.item_id)} />
                      </td>
                      <td className="px-2 py-2 truncate max-w-[300px]" title={item.title}>{item.title || '(无标题)'}</td>
                      <td className="px-2 py-2 truncate text-on-surface-variant">
                        {item.creators.slice(0, 2).map(c => c.last_name || c.first_name).join(', ') || '-'}
                      </td>
                      <td className="px-2 py-2 text-on-surface-variant">{item.date ? item.date.slice(0, 4) : '-'}</td>
                      <td className="px-2 py-2 text-center">{item.pdf_paths.length > 0 ? '✓' : '✗'}</td>
                      <td className="px-2 py-2 text-center">{item.note_count > 0 ? '✓' : '✗'}</td>
                      <td className="px-2 py-2 text-center">{item.annotation_count > 0 ? '✓' : '✗'}</td>
                    </tr>
                  ))}
                  {filteredItems.length === 0 && scanResult && (
                    <tr><td colSpan={7} className="text-center py-8 text-sm text-outline">无匹配条目</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right — Detail preview */}
          <div className="w-80 border-l border-outline-variant overflow-y-auto shrink-0 p-4">
            {previewItem ? (
              <div className="space-y-3 text-sm">
                <h3 className="font-bold text-on-surface">{previewItem.title || '(无标题)'}</h3>
                {previewItem.creators.length > 0 && (
                  <div>
                    <div className="text-xs text-outline font-bold uppercase mb-1">作者</div>
                    <div className="text-on-surface-variant">
                      {previewItem.creators.map(c => `${c.last_name}, ${c.first_name} (${c.creator_type})`).join('; ')}
                    </div>
                  </div>
                )}
                {previewItem.date && (
                  <div>
                    <div className="text-xs text-outline font-bold uppercase mb-1">年份</div>
                    <div className="text-on-surface-variant">{previewItem.date}</div>
                  </div>
                )}
                {previewItem.publication_title && (
                  <div>
                    <div className="text-xs text-outline font-bold uppercase mb-1">期刊</div>
                    <div className="text-on-surface-variant">{previewItem.publication_title}{previewItem.volume ? ` ${previewItem.volume}` : ''}{previewItem.issue ? `(${previewItem.issue})` : ''}{previewItem.pages ? `: ${previewItem.pages}` : ''}</div>
                  </div>
                )}
                {previewItem.doi && (
                  <div>
                    <div className="text-xs text-outline font-bold uppercase mb-1">DOI</div>
                    <div className="text-on-surface-variant font-mono text-xs">{previewItem.doi}</div>
                  </div>
                )}
                {previewItem.abstract && (
                  <div>
                    <div className="text-xs text-outline font-bold uppercase mb-1">摘要</div>
                    <div className="text-on-surface-variant text-xs leading-relaxed line-clamp-6">{previewItem.abstract}</div>
                  </div>
                )}
                {previewItem.collections.length > 0 && (
                  <div>
                    <div className="text-xs text-outline font-bold uppercase mb-1">文件夹</div>
                    <div className="text-on-surface-variant text-xs">{previewItem.collections.join(' > ')}</div>
                  </div>
                )}
                <div className="text-xs text-outline font-bold uppercase">PDF 路径</div>
                <div className="text-on-surface-variant text-xs font-mono break-all">{previewItem.pdf_paths[0] || '无'}</div>
                <div className="flex gap-4 text-xs text-outline pt-1">
                  <span>笔记: {previewItem.note_count}</span>
                  <span>标注: {previewItem.annotation_count}</span>
                </div>
              </div>
            ) : (
              <div className="text-sm text-outline text-center mt-12">点击左侧条目查看详情</div>
            )}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="px-6 py-3 border-t border-outline-variant flex items-center gap-3 shrink-0">
          <label className="text-sm text-on-surface-variant shrink-0">目标文献库:</label>
          <select
            value={targetLibrary}
            onChange={e => setTargetLibrary(e.target.value)}
            className="bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-secondary"
          >
            {libraries.map(lib => (
              <option key={lib.library_id} value={lib.library_id}>{lib.library_id}</option>
            ))}
          </select>
          <div className="flex-1" />
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm text-on-surface-variant hover:bg-surface-container transition-colors">
            取消
          </button>
          <button
            onClick={handleImport}
            disabled={selectedIds.size === 0 || importing}
            className="bg-secondary text-on-secondary px-6 py-2 rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50 transition-all"
          >
            {importing ? '导入中...' : `导入选中 (${selectedIds.size})`}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd D:/Code/kn_gragh/scholarai-workbench && npx tsc --noEmit
```

Fix any type errors.

- [ ] **Step 3: Commit**

```bash
cd D:/Code/kn_gragh && git add scholarai-workbench/src/components/ZoteroImportModal.tsx && git commit -m "feat: add ZoteroImportModal component with folder tree, item table, and detail preview"
```

---

### Task 8: Frontend — Add button to PipelineView

**Files:**
- Modify: `scholarai-workbench/src/components/PipelineView.tsx`

- [ ] **Step 1: Add import and state for Zotero modal**

At the top of `PipelineView.tsx`, add the import:

```tsx
import ZoteroImportModal from './ZoteroImportModal';
```

Add state after existing state declarations:

```tsx
const [showZoteroModal, setShowZoteroModal] = useState(false);
```

- [ ] **Step 2: Add the button next to the upload area**

In the "上传 PDF" card, find the button area (around line 502-520). Add the Zotero button before the existing `<button>` that says "导入选中文件":

```tsx
{/* Add this button group before the import button */}
<div className="flex items-center gap-3">
  <button
    onClick={() => setShowZoteroModal(true)}
    className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-bold border-2 border-secondary text-secondary hover:bg-secondary-container/10 transition-all"
  >
    <Database className="w-4 h-4" />
    从 Zotero 导入
  </button>
  {/* Existing import button */}
  <button
    onClick={submitJob}
    ...
  >
    ...
  </button>
</div>
```

Add `Database` to the lucide-react imports at the top.

- [ ] **Step 3: Add the modal at the end of the component**

Before the final `</>` of the component return (before the last closing fragment tag), add:

```tsx
      <ZoteroImportModal open={showZoteroModal} onClose={() => setShowZoteroModal(false)} />
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd D:/Code/kn_gragh/scholarai-workbench && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
cd D:/Code/kn_gragh && git add scholarai-workbench/src/components/PipelineView.tsx && git commit -m "feat: add '从 Zotero 导入' button to import page"
```

---

### Task 9: End-to-end integration testing

- [ ] **Step 1: Start the development server**

```bash
cd D:/Code/kn_gragh && uv run python -m kn_graph serve --port 8013
```

- [ ] **Step 2: Start the frontend dev server**

```bash
cd D:/Code/kn_gragh/scholarai-workbench && npm run dev
```

- [ ] **Step 3: Manual test checklist**

1. Navigate to the "文献导入" (pipeline) page
2. Click "从 Zotero 导入" — modal opens
3. Enter Zotero data directory (or leave blank for auto-detect)
4. Click "扫描" — verify items appear in table
5. Filter by folder — verify filtering works
6. Search by title/author — verify search works
7. Click an item — verify detail preview in right panel
8. Select multiple items using checkboxes
9. Select a target library from the dropdown
10. Click "导入选中" — verify jobs appear in the task table
11. Verify jobs progress through stages
12. After completion, verify papers appear in the library

- [ ] **Step 4: Commit any fixes needed**

---

## Summary of Commits

1. `feat: add Zotero scanner module for reading local zotero.sqlite`
2. `feat: add Zotero Pydantic models for scan/import API`
3. `feat: add /zotero/scan and /zotero/import API endpoints`
4. `feat: inject Zotero notes/annotations into markdown, merge Zotero metadata into extraction`
5. `feat: add Zotero TypeScript types`
6. `feat: add Zotero API functions to frontend`
7. `feat: add ZoteroImportModal component with folder tree, item table, and detail preview`
8. `feat: add '从 Zotero 导入' button to import page`
