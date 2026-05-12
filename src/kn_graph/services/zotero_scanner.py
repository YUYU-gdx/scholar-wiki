"""
Zotero SQLite scanner.

Provides two entry points:
  - scan_zotero(data_dir)   -- return all literature-type items with existing PDF attachments
  - get_zotero_item_full(data_dir, item_id) -- return full detail for one item (notes + annotations)

Helper functions:
  - _find_data_dir()            -- auto-detect from prefs.js (Windows only)
  - _safe_open_zotero_db()      -- copy zotero.sqlite to a temp file, open read-only
  - _cleanup_temp_db()          -- remove the temp copy
  - _resolve_attachment_path()  -- normalise storage:/attachments:/absolute-path
"""

import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_zotero(data_dir: str = "") -> dict[str, Any]:
    """Scan a Zotero data directory and return literature items that have at
    least one PDF attachment whose file exists on disk.

    Parameters
    ----------
    data_dir : str
        Path to the Zotero data directory.  If empty / falsy the function
        will attempt to auto-detect the directory from the Zotero profile's
        ``prefs.js`` (Windows).

    Returns
    -------
    dict
        ``{"items": [item, ...], "total_count": N}`` where each *item* is a
        flat dictionary containing metadata, creators, PDF paths, notes /
        annotation counts, and collection names.
    """
    if not data_dir:
        data_dir = _find_data_dir()

    conn, tmp_path = _safe_open_zotero_db(data_dir)
    try:
        conn.row_factory = sqlite3.Row

        # --- lookup tables -------------------------------------------------
        type_map = _dict_from(conn, "SELECT itemTypeID, typeName FROM itemTypes")
        field_map = _dict_from(conn, "SELECT fieldID, fieldName FROM fields")

        exclude_type_ids = [
            tid for tid, tn in type_map.items()
            if tn in ("attachment", "note", "annotation")
        ]

        base_dir = _read_setting(conn, "baseDir", "baseDir")

        # --- literature items ----------------------------------------------
        if exclude_type_ids:
            placeholders = ",".join("?" * len(exclude_type_ids))
            rows = conn.execute(
                f"SELECT itemID, itemTypeID, key, dateAdded, dateModified, libraryID "
                f"FROM items WHERE itemTypeID NOT IN ({placeholders})",
                exclude_type_ids,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT itemID, itemTypeID, key, dateAdded, dateModified, libraryID "
                "FROM items"
            ).fetchall()

        lit_items = {}
        for r in rows:
            lit_items[r["itemID"]] = {
                "item_id": r["itemID"],
                "item_type_id": r["itemTypeID"],
                "item_type": type_map.get(r["itemTypeID"], "unknown"),
                "key": r["key"],
                "date_added": r["dateAdded"],
                "date_modified": r["dateModified"],
                "library_id": r["libraryID"],
                "metadata": {},
                "creators": [],
                "pdf_paths": [],
                "note_count": 0,
                "annotation_count": 0,
                "collections": [],
            }

        if not lit_items:
            return {"items": [], "total_count": 0}

        item_ids = list(lit_items.keys())
        id_ph = ",".join("?" * len(item_ids))

        # --- EAV metadata --------------------------------------------------
        _attach_metadata(conn, lit_items, item_ids, id_ph, field_map)

        # --- creators ------------------------------------------------------
        _attach_creators(conn, lit_items, item_ids, id_ph)

        # --- attachments (PDF) ---------------------------------------------
        _attach_pdfs(conn, lit_items, item_ids, id_ph, data_dir, base_dir)

        # --- notes ---------------------------------------------------------
        _attach_note_counts(conn, lit_items, item_ids, id_ph)

        # --- annotations ---------------------------------------------------
        _attach_annotation_counts(conn, lit_items, item_ids, id_ph)

        # --- collections ---------------------------------------------------
        _attach_collections(conn, lit_items, item_ids, id_ph)

        # --- filter to items with at least one existing PDF ----------------
        result_items = [v for v in lit_items.values() if v["pdf_paths"]]

        output = []
        for item in result_items:
            md = item["metadata"]
            output.append({
                "item_id": item["item_id"],
                "item_type": item["item_type"],
                "key": item["key"],
                "title": md.get("title", ""),
                "date": md.get("date", ""),
                "publication_title": md.get("publicationTitle", ""),
                "volume": md.get("volume", ""),
                "issue": md.get("issue", ""),
                "pages": md.get("pages", ""),
                "doi": md.get("DOI", ""),
                "abstract": md.get("abstractNote", ""),
                "url": md.get("url", ""),
                "creators": item["creators"],
                "pdf_paths": item["pdf_paths"],
                "note_count": item["note_count"],
                "annotation_count": item["annotation_count"],
                "collections": item["collections"],
            })

        # Also return all collections as a top-level list
        all_collections = _load_all_collections(conn)

        return {"items": output, "total_count": len(output), "collections": all_collections}

    finally:
        _cleanup_temp_db(tmp_path)


def get_zotero_item_full(data_dir: str, item_id: int) -> dict[str, Any] | None:
    """Return full detail for a single Zotero item, including notes content
    and annotation texts (sorted by ``sortIndex``).

    Unlike ``scan_zotero``, this function returns data regardless of whether
    the PDF file currently exists on disk.

    Parameters
    ----------
    data_dir : str
        Path to the Zotero data directory.
    item_id : int
        The ``itemID`` in the Zotero SQLite database.

    Returns
    -------
    dict or None
        Full item detail, or ``None`` if the item ID is not found.
    """
    conn, tmp_path = _safe_open_zotero_db(data_dir)
    try:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            "SELECT i.*, it.typeName FROM items i "
            "JOIN itemTypes it ON i.itemTypeID = it.itemTypeID "
            "WHERE i.itemID = ?",
            (item_id,),
        ).fetchone()

        if row is None:
            return None

        result = {
            "item_id": row["itemID"],
            "key": row["key"],
            "item_type": row["typeName"],
            "date_added": row["dateAdded"],
            "date_modified": row["dateModified"],
            "library_id": row["libraryID"],
            "metadata": {},
            "creators": [],
            "pdf_paths": [],
            "notes": [],
            "annotations": [],
            "collections": [],
        }

        field_map = _dict_from(conn, "SELECT fieldID, fieldName FROM fields")
        base_dir = _read_setting(conn, "baseDir", "baseDir")

        # Metadata
        for r in conn.execute(
            "SELECT id.fieldID, idv.value FROM itemData id "
            "JOIN itemDataValues idv ON id.valueID = idv.valueID "
            "WHERE id.itemID = ?",
            (item_id,),
        ):
            name = field_map.get(r["fieldID"], f"field_{r['fieldID']}")
            result["metadata"][name] = r["value"]

        # Creators
        for r in conn.execute(
            "SELECT cr.firstName, cr.lastName, cr.fieldMode, ct.creatorType "
            "FROM itemCreators ic "
            "JOIN creators cr ON ic.creatorID = cr.creatorID "
            "JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID "
            "WHERE ic.itemID = ? ORDER BY ic.orderIndex",
            (item_id,),
        ):
            result["creators"].append({
                "first_name": r["firstName"] or "",
                "last_name": r["lastName"] or "",
                "field_mode": r["fieldMode"],
                "creator_type": r["creatorType"],
            })

        # Attachments
        for r in conn.execute(
            "SELECT ia.itemID AS attachment_id, ia.linkMode, ia.contentType, "
            "       ia.path, i.key AS attachment_key "
            "FROM itemAttachments ia "
            "JOIN items i ON ia.itemID = i.itemID "
            "WHERE ia.parentItemID = ?",
            (item_id,),
        ):
            resolved = _resolve_attachment_path(
                r["path"], r["attachment_key"], data_dir, base_dir
            )
            result["pdf_paths"].append({
                "attachment_id": r["attachment_id"],
                "content_type": r["contentType"],
                "path": r["path"],
                "resolved_path": resolved,
                "file_exists": resolved is not None and os.path.isfile(resolved),
            })

        # Notes (full content)
        for r in conn.execute(
            "SELECT itemID, title, note FROM itemNotes "
            "WHERE parentItemID = ? ORDER BY itemID",
            (item_id,),
        ):
            result["notes"].append({
                "note_id": r["itemID"],
                "title": r["title"],
                "content": r["note"],
            })

        # Annotations (sorted by sortIndex)
        # Annotations are children of the PDF attachment, not the article.
        # Collect annotation-bearing descendant IDs from itemAttachments.
        ann_targets = [item_id]
        for r in conn.execute(
            "SELECT itemID FROM itemAttachments WHERE parentItemID = ?",
            (item_id,),
        ):
            ann_targets.append(r["itemID"])

        target_ph = ",".join("?" * len(ann_targets))
        for r in conn.execute(
            f"SELECT itemID, type, authorName, text, comment, color, "
            f"       pageLabel, sortIndex, position "
            f"FROM itemAnnotations "
            f"WHERE parentItemID IN ({target_ph}) ORDER BY sortIndex",
            ann_targets,
        ):
            result["annotations"].append({
                "annotation_id": r["itemID"],
                "type": r["type"],
                "author_name": r["authorName"],
                "text": r["text"],
                "comment": r["comment"],
                "color": r["color"],
                "page_label": r["pageLabel"],
                "sort_index": r["sortIndex"],
                "position": r["position"],
            })

        # Collections
        for r in conn.execute(
            "SELECT c.collectionName FROM collectionItems ci "
            "JOIN collections c ON ci.collectionID = c.collectionID "
            "WHERE ci.itemID = ?",
            (item_id,),
        ):
            result["collections"].append(r["collectionName"])

        return result

    finally:
        _cleanup_temp_db(tmp_path)


def get_zotero_items_batch(data_dir: str, item_ids: list[int]) -> list[dict[str, Any]]:
    """Like ``get_zotero_item_full`` but copies the database only once for
    multiple items.  Items that can't be found are silently skipped."""
    if not item_ids:
        return []
    data_dir = os.path.expanduser(data_dir)
    conn, tmp_path = _safe_open_zotero_db(data_dir)
    try:
        conn.row_factory = sqlite3.Row
        results: list[dict[str, Any]] = []
        for item_id in item_ids:
            row = conn.execute(
                "SELECT i.*, it.typeName FROM items i "
                "JOIN itemTypes it ON i.itemTypeID = it.itemTypeID "
                "WHERE i.itemID = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                continue
            result = {
                "item_id": row["itemID"],
                "key": row["key"],
                "item_type": row["typeName"],
                "date_added": row["dateAdded"],
                "date_modified": row["dateModified"],
                "library_id": row["libraryID"],
                "metadata": {},
                "creators": [],
                "pdf_paths": [],
                "notes": [],
                "annotations": [],
                "collections": [],
            }
            field_map = _dict_from(conn, "SELECT fieldID, fieldName FROM fields")
            base_dir = _read_setting(conn, "baseDir", "baseDir")
            # Metadata
            for r2 in conn.execute(
                "SELECT id.fieldID, idv.value FROM itemData id "
                "JOIN itemDataValues idv ON id.valueID = idv.valueID "
                "WHERE id.itemID = ?",
                (item_id,),
            ):
                name = field_map.get(r2["fieldID"], f"field_{r2['fieldID']}")
                result["metadata"][name] = r2["value"]
            # Creators
            for r2 in conn.execute(
                "SELECT cr.firstName, cr.lastName, cr.fieldMode, ct.creatorType "
                "FROM itemCreators ic "
                "JOIN creators cr ON ic.creatorID = cr.creatorID "
                "JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID "
                "WHERE ic.itemID = ? ORDER BY ic.orderIndex",
                (item_id,),
            ):
                result["creators"].append({
                    "first_name": r2["firstName"] or "",
                    "last_name": r2["lastName"] or "",
                    "field_mode": r2["fieldMode"],
                    "creator_type": r2["creatorType"],
                })
            # Attachments
            for r2 in conn.execute(
                "SELECT ia.itemID AS attachment_id, ia.linkMode, ia.contentType, "
                "       ia.path, i2.key AS attachment_key "
                "FROM itemAttachments ia "
                "JOIN items i2 ON ia.itemID = i2.itemID "
                "WHERE ia.parentItemID = ?",
                (item_id,),
            ):
                resolved = _resolve_attachment_path(r2["path"], r2["attachment_key"], data_dir, base_dir)
                result["pdf_paths"].append({
                    "attachment_id": r2["attachment_id"],
                    "content_type": r2["contentType"],
                    "path": r2["path"],
                    "resolved_path": resolved,
                    "file_exists": resolved is not None and os.path.isfile(resolved),
                })
            # Notes
            for r2 in conn.execute(
                "SELECT itemID, title, note FROM itemNotes WHERE parentItemID = ? ORDER BY itemID",
                (item_id,),
            ):
                result["notes"].append({
                    "note_id": r2["itemID"], "title": r2["title"], "content": r2["note"],
                })
            # Annotations
            ann_targets = [item_id]
            for r2 in conn.execute(
                "SELECT itemID FROM itemAttachments WHERE parentItemID = ?", (item_id,),
            ):
                ann_targets.append(r2["itemID"])
            target_ph = ",".join("?" * len(ann_targets))
            for r2 in conn.execute(
                f"SELECT itemID, type, authorName, text, comment, color, "
                f"       pageLabel, sortIndex, position "
                f"FROM itemAnnotations "
                f"WHERE parentItemID IN ({target_ph}) ORDER BY sortIndex",
                ann_targets,
            ):
                result["annotations"].append({
                    "annotation_id": r2["itemID"], "type": r2["type"],
                    "author_name": r2["authorName"], "text": r2["text"],
                    "comment": r2["comment"], "color": r2["color"],
                    "page_label": r2["pageLabel"], "sort_index": r2["sortIndex"],
                    "position": r2["position"],
                })
            # Collections
            for r2 in conn.execute(
                "SELECT c.collectionName FROM collectionItems ci "
                "JOIN collections c ON ci.collectionID = c.collectionID "
                "WHERE ci.itemID = ?",
                (item_id,),
            ):
                result["collections"].append(r2["collectionName"])
            results.append(result)
        return results
    finally:
        _cleanup_temp_db(tmp_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_data_dir():
    """Auto-detect the Zotero data directory by inspecting the Firefox-style
    ``prefs.js`` of the active Zotero profile.

    Currently supports Windows only (``%APPDATA%/Zotero/Zotero/Profiles/``).
    """
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            profiles_dir = os.path.join(appdata, "Zotero", "Zotero", "Profiles")
            if os.path.isdir(profiles_dir):
                for entry in os.listdir(profiles_dir):
                    prefs = os.path.join(profiles_dir, entry, "prefs.js")
                    if os.path.isfile(prefs):
                        value = _extract_data_dir_from_prefs(prefs)
                        if value:
                            return value

    raise FileNotFoundError(
        "Could not auto-detect Zotero data directory. "
        "Please provide an explicit data_dir path."
    )


def _extract_data_dir_from_prefs(prefs_path):
    """Parse *prefs.js* and return the value of ``extensions.zotero.dataDir``,
    or ``None``.
    """
    with open(prefs_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if "extensions.zotero.dataDir" not in line:
                continue
            # user_pref("extensions.zotero.dataDir", "C:\\Users\\...");
            # The value is the last quoted string in the line.
            matches = re.findall(r'"([^"]*)"', line)
            if len(matches) >= 2:
                val = matches[-1]
                # Normalise Windows path separators
                val = val.replace("\\\\", "/").replace("\\", "/")
                return val
    return None


def _safe_open_zotero_db(data_dir):
    """Make a temporary copy of ``zotero.sqlite`` and return ``(connection,
    temp_path)``.
    """
    src = os.path.join(data_dir, "zotero.sqlite")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"zotero.sqlite not found in: {data_dir}")

    fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    shutil.copy2(src, tmp_path)

    conn = sqlite3.connect(tmp_path)
    return conn, tmp_path


def _cleanup_temp_db(tmp_path):
    """Remove the temporary database copy."""
    try:
        os.unlink(tmp_path)
    except (OSError, FileNotFoundError):
        pass


def _resolve_attachment_path(path, item_key, data_dir, base_dir):
    """Resolve a Zotero attachment *path* to an absolute filesystem path.

    Three forms are supported:

    * ``storage:<filename>``     -- data_dir/storage/<item_key>/<filename>
    * ``attachments:<rel>``      -- base_dir/<rel>
    * absolute path             -- returned as-is
    """
    if not path:
        return None

    if path.startswith("storage:"):
        filename = path[len("storage:"):]
        return os.path.join(
            data_dir, "storage", item_key, filename
        )

    if path.startswith("attachments:"):
        rel = path[len("attachments:"):]
        if base_dir:
            return os.path.join(base_dir, rel)
        return None

    # Absolute path
    return path


# ---------------------------------------------------------------------------
# Query helpers (used by scan_zotero)
# ---------------------------------------------------------------------------


def _dict_from(conn, sql, params=None):
    """Execute *sql* and return a ``{first_col: second_col}`` dictionary."""
    rows = conn.execute(sql, params or []).fetchall()
    return {r[0]: r[1] for r in rows}


def _read_setting(conn, setting, key):
    """Read a value from the Zotero ``settings`` table, or return ``None``."""
    row = conn.execute(
        "SELECT value FROM settings WHERE setting=? AND key=?", (setting, key)
    ).fetchone()
    return row["value"] if row else None


def _attach_metadata(conn, lit_items, item_ids, id_ph, field_map):
    """Add EAV (itemData) fields into each lit_item's ``metadata`` dict."""
    for r in conn.execute(
        f"SELECT id.itemID, id.fieldID, idv.value "
        f"FROM itemData id "
        f"JOIN itemDataValues idv ON id.valueID = idv.valueID "
        f"WHERE id.itemID IN ({id_ph})",
        item_ids,
    ):
        name = field_map.get(r["fieldID"], f"field_{r['fieldID']}")
        lit_items[r["itemID"]]["metadata"][name] = r["value"]


def _attach_creators(conn, lit_items, item_ids, id_ph):
    """Add creator info to each lit_item."""
    for r in conn.execute(
        f"SELECT ic.itemID, cr.firstName, cr.lastName, cr.fieldMode, "
        f"       ct.creatorType "
        f"FROM itemCreators ic "
        f"JOIN creators cr ON ic.creatorID = cr.creatorID "
        f"JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID "
        f"WHERE ic.itemID IN ({id_ph}) "
        f"ORDER BY ic.itemID, ic.orderIndex",
        item_ids,
    ):
        lit_items[r["itemID"]]["creators"].append({
            "first_name": r["firstName"] or "",
            "last_name": r["lastName"] or "",
            "field_mode": r["fieldMode"],
            "creator_type": r["creatorType"],
        })


def _attach_pdfs(conn, lit_items, item_ids, id_ph, data_dir, base_dir):
    """Resolve attachment paths and store them on the parent lit_item if the
    file exists on disk.
    """
    for r in conn.execute(
        f"SELECT ia.parentItemID, ia.path, i.key AS attachment_key "
        f"FROM itemAttachments ia "
        f"JOIN items i ON ia.itemID = i.itemID "
        f"WHERE ia.parentItemID IN ({id_ph}) "
        f"  AND ia.contentType = 'application/pdf'",
        item_ids,
    ):
        resolved = _resolve_attachment_path(
            r["path"], r["attachment_key"], data_dir, base_dir
        )
        if resolved and os.path.isfile(resolved):
            lit_items[r["parentItemID"]]["pdf_paths"].append(resolved)


def _attach_note_counts(conn, lit_items, item_ids, id_ph):
    """Count notes per parent item.

    Notes may be attached either directly to the literature item or to one of
    its descendants (e.g. the PDF attachment).
    """
    # Build set of all descendant IDs for literature items
    descendant_map = _build_child_map(conn, item_ids, id_ph)

    for r in conn.execute(
        f"SELECT parentItemID, COUNT(*) AS cnt FROM itemNotes "
        f"WHERE parentItemID IN ({id_ph}) GROUP BY parentItemID",
        item_ids,
    ):
        lit_items[r["parentItemID"]]["note_count"] = r["cnt"]

    # Also count notes attached to descendants
    for parent_id, children in descendant_map.items():
        if not children:
            continue
        child_ph = ",".join("?" * len(children))
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM itemNotes "
            f"WHERE parentItemID IN ({child_ph})",
            children,
        ).fetchone()
        if row and row["cnt"]:
            lit_items[parent_id]["note_count"] += row["cnt"]


def _attach_annotation_counts(conn, lit_items, item_ids, id_ph):
    """Count annotations per parent item.

    In Zotero, annotations are usually children of the **PDF attachment**,
    not the top-level literature item.  We walk through attachments to find
    them, but also count any annotations attached directly to the item.
    """
    # Direct annotations (unusual but possible)
    for r in conn.execute(
        f"SELECT parentItemID, COUNT(*) AS cnt FROM itemAnnotations "
        f"WHERE parentItemID IN ({id_ph}) GROUP BY parentItemID",
        item_ids,
    ):
        lit_items[r["parentItemID"]]["annotation_count"] += r["cnt"]

    # Annotations on descendant attachments
    descendant_map = _build_child_map(conn, item_ids, id_ph)

    for parent_id, children in descendant_map.items():
        if not children:
            continue
        child_ph = ",".join("?" * len(children))
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM itemAnnotations "
            f"WHERE parentItemID IN ({child_ph})",
            children,
        ).fetchone()
        if row and row["cnt"]:
            lit_items[parent_id]["annotation_count"] += row["cnt"]


def _build_child_map(conn, parent_ids, parent_ph):
    """Build ``{parent_itemID: [child_itemID, ...]}`` from
    ``itemAttachments`` whose ``parentItemID`` is in *parent_ids*.

    This is used to find annotation-holding attachments that belong to
    a literature item (annotations are children of the PDF attachment,
    not the article directly).
    """
    mapping = {pid: [] for pid in parent_ids}
    for r in conn.execute(
        f"SELECT itemID, parentItemID FROM itemAttachments "
        f"WHERE parentItemID IN ({parent_ph})",
        parent_ids,
    ):
        mapping[r["parentItemID"]].append(r["itemID"])
    return mapping


def _attach_collections(conn, lit_items, item_ids, id_ph):
    """Add collection names to each lit_item."""
    for r in conn.execute(
        f"SELECT ci.itemID, c.collectionName "
        f"FROM collectionItems ci "
        f"JOIN collections c ON ci.collectionID = c.collectionID "
        f"WHERE ci.itemID IN ({id_ph})",
        item_ids,
    ):
        name = r["collectionName"]
        item = lit_items[r["itemID"]]
        if name not in item["collections"]:
            item["collections"].append(name)


def _load_all_collections(conn) -> list[dict[str, Any]]:
    """Load all collections as a flat list with id, name, parent_id."""
    result = []
    for r in conn.execute(
        "SELECT collectionID, collectionName, parentCollectionID FROM collections ORDER BY collectionName"
    ):
        result.append({
            "collection_id": r["collectionID"],
            "name": r["collectionName"],
            "parent_id": r["parentCollectionID"],
        })
    return result
