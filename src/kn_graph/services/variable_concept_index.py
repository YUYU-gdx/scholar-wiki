from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any


_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def _lookup_key(text: str) -> str:
    return " ".join(_tokens(text))


def _variable_name_norm(text: str) -> str:
    parts = _tokens(text)
    return "_".join(parts) if parts else "unknown"


def _hash_embedding(text: str, dim: int = 256) -> list[float]:
    vec = [0.0] * dim
    toks = _tokens(text)
    if not toks:
        return vec
    for tok in toks:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = -1.0 if (digest[4] & 1) else 1.0
        vec[idx] += sign
    norm = sum(v * v for v in vec) ** 0.5
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def _dedupe_texts(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        txt = str(raw or "").strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


class _VariableConceptChromaClient:
    COLLECTION_NAME = "variable_concepts_v1"

    def __init__(self, persist_dir: Path) -> None:
        import chromadb

        self._persist_dir = persist_dir
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection: Any | None = None

    def _get_collection(self) -> Any:
        if self._collection is None:
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def existing_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        col = self._get_collection()
        rows = col.get(ids=ids, include=[])
        current = rows.get("ids", []) if isinstance(rows, dict) else []
        return {str(x) for x in current}

    def upsert_many(self, rows: list[tuple[str, str, dict[str, Any], list[float]]]) -> None:
        if not rows:
            return
        ids: list[str] = []
        docs: list[str] = []
        metadatas: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        for doc_id, text, metadata, embedding in rows:
            ids.append(doc_id)
            docs.append(text)
            metadatas.append(dict(metadata))
            embeddings.append(list(embedding))
        col = self._get_collection()
        col.upsert(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings)

    def query(self, *, library_id: str, query_embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        col = self._get_collection()
        rows = col.query(
            query_embeddings=[query_embedding],
            n_results=max(1, int(top_k)),
            where={"library_id": str(library_id)},
            include=["metadatas", "documents", "distances"],
        )
        ids = rows.get("ids", [[]])[0] if isinstance(rows, dict) else []
        metadatas = rows.get("metadatas", [[]])[0] if isinstance(rows, dict) else []
        documents = rows.get("documents", [[]])[0] if isinstance(rows, dict) else []
        distances = rows.get("distances", [[]])[0] if isinstance(rows, dict) else []

        out: list[dict[str, Any]] = []
        for doc_id, metadata, document, distance in zip(ids, metadatas, documents, distances):
            dist_val = float(distance) if isinstance(distance, (int, float)) else 0.0
            out.append(
                {
                    "id": str(doc_id or ""),
                    "score": 1.0 / (1.0 + max(0.0, dist_val)),
                    "metadata": dict(metadata or {}),
                    "document": str(document or ""),
                }
            )
        return out


class VariableConceptIndexService:
    def __init__(self, workspace_path: str = "") -> None:
        ws = str(workspace_path or "").strip()
        self._workspace_path = Path(ws).resolve() if ws else None
        self._library_workspace: dict[str, Path] = {}
        self._clients: dict[str, _VariableConceptChromaClient] = {}

    def upsert_paper_variable_concepts(self, library_id: str, paper_id: str, db_path: str) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        pid = str(paper_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if not pid:
            raise ValueError("paper_id_required")

        workspace = self._resolve_workspace(library_id=lib, db_path=db_path)
        persist_dir = workspace / "corpus" / "variables_concept_index"
        chroma = self._get_chroma(persist_dir)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            alias_to_canonical, aliases_by_canonical = self._build_alias_index(conn)
            rows = conn.execute(
                """
                SELECT variable_name, definition_text
                FROM variable_definitions
                WHERE paper_id = ? AND trim(definition_text) <> ''
                """,
                (pid,),
            ).fetchall()
        finally:
            conn.close()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            variable_name = str(row["variable_name"] or "").strip()
            definition_text = str(row["definition_text"] or "").strip()
            if not variable_name or not definition_text:
                continue
            variable_norm = _variable_name_norm(variable_name)
            bucket = grouped.setdefault(
                variable_norm,
                {
                    "variable_name": variable_name,
                    "variable_name_norm": variable_norm,
                    "definitions": [],
                },
            )
            bucket["definitions"].append(definition_text)

        upsert_rows: list[tuple[str, str, dict[str, Any], list[float]]] = []
        for variable_norm, payload in grouped.items():
            variable_name = str(payload["variable_name"])
            definitions = _dedupe_texts([str(x) for x in payload["definitions"]])
            concept_text = "\n".join(definitions).strip()
            if not concept_text:
                continue
            candidate_ids = sorted(alias_to_canonical.get(_lookup_key(variable_name), set()))
            canonical_var_id = candidate_ids[0] if candidate_ids else ""
            aliases = aliases_by_canonical.get(canonical_var_id, [])
            search_text = " ".join(_dedupe_texts([variable_name, *aliases, concept_text]))
            doc_id = f"{lib}::{pid}::{variable_norm}"
            metadata = {
                "library_id": lib,
                "paper_id": pid,
                "variable_name": variable_name,
                "variable_name_norm": variable_norm,
                "canonical_var_id": canonical_var_id,
                "updated_at": _now_iso(),
            }
            upsert_rows.append((doc_id, concept_text, metadata, _hash_embedding(search_text)))

        existing = chroma.existing_ids([r[0] for r in upsert_rows])
        chroma.upsert_many(upsert_rows)
        upserted = sum(1 for row in upsert_rows if row[0] not in existing)
        updated = len(upsert_rows) - upserted
        return {
            "library_id": lib,
            "paper_id": pid,
            "workspace_path": str(workspace),
            "persist_dir": str(persist_dir),
            "upserted": upserted,
            "updated": updated,
            "total": len(upsert_rows),
        }

    def query(self, library_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        lib = str(library_id or "").strip()
        text = str(query or "").strip()
        if not lib or not text:
            return []
        workspace = self._resolve_workspace(library_id=lib, db_path="")
        persist_dir = workspace / "corpus" / "variables_concept_index"
        chroma = self._get_chroma(persist_dir)
        rows = chroma.query(library_id=lib, query_embedding=_hash_embedding(text), top_k=top_k)

        hits: list[dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
            hits.append(
                {
                    "id": str(row.get("id", "") or ""),
                    "score": float(row.get("score", 0.0) or 0.0),
                    "library_id": str(metadata.get("library_id", "") or ""),
                    "paper_id": str(metadata.get("paper_id", "") or ""),
                    "variable_name": str(metadata.get("variable_name", "") or ""),
                    "variable_name_norm": str(metadata.get("variable_name_norm", "") or ""),
                    "canonical_var_id": str(metadata.get("canonical_var_id", "") or ""),
                    "concept_text": str(row.get("document", "") or ""),
                }
            )
        return hits

    def expand_aliases(self, db_path: str, canonical_var_ids: list[str]) -> dict[str, list[str]]:
        canonical_ids = [str(v or "").strip() for v in canonical_var_ids if str(v or "").strip()]
        if not canonical_ids:
            return {}
        canonical_ids = list(dict.fromkeys(canonical_ids))

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join(["?"] * len(canonical_ids))
            canonical_rows = conn.execute(
                f"""
                SELECT canonical_var_id, canonical_name
                FROM canonical_variables
                WHERE canonical_var_id IN ({placeholders})
                """,
                tuple(canonical_ids),
            ).fetchall()
            alias_rows = conn.execute(
                f"""
                SELECT canonical_var_id, alias_text
                FROM variable_aliases
                WHERE canonical_var_id IN ({placeholders})
                ORDER BY id ASC
                """,
                tuple(canonical_ids),
            ).fetchall()
        finally:
            conn.close()

        out: dict[str, list[str]] = {cid: [] for cid in canonical_ids}
        for row in canonical_rows:
            cid = str(row["canonical_var_id"] or "")
            if cid in out:
                out[cid].append(str(row["canonical_name"] or ""))
        for row in alias_rows:
            cid = str(row["canonical_var_id"] or "")
            if cid in out:
                out[cid].append(str(row["alias_text"] or ""))
        for cid, values in out.items():
            out[cid] = _dedupe_texts(values)
        return out

    def _resolve_workspace(self, *, library_id: str, db_path: str) -> Path:
        lib = str(library_id or "").strip()
        db = str(db_path or "").strip()
        if db:
            workspace = Path(db).resolve().parent
            if lib:
                self._library_workspace[lib] = workspace
            return workspace
        if lib and lib in self._library_workspace:
            return self._library_workspace[lib]
        if self._workspace_path is not None:
            if lib:
                self._library_workspace[lib] = self._workspace_path
            return self._workspace_path
        raise ValueError("workspace_path_required")

    def _get_chroma(self, persist_dir: Path) -> _VariableConceptChromaClient:
        key = str(persist_dir.resolve())
        if key not in self._clients:
            self._clients[key] = _VariableConceptChromaClient(persist_dir)
        return self._clients[key]

    def _build_alias_index(self, conn: sqlite3.Connection) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
        alias_to_canonical: dict[str, set[str]] = defaultdict(set)
        aliases_by_canonical: dict[str, list[str]] = defaultdict(list)

        canonical_rows = conn.execute("SELECT canonical_var_id, canonical_name FROM canonical_variables").fetchall()
        for row in canonical_rows:
            cid = str(row["canonical_var_id"] or "").strip()
            cname = str(row["canonical_name"] or "").strip()
            if not cid:
                continue
            aliases_by_canonical[cid].append(cname)
            key = _lookup_key(cname)
            if key:
                alias_to_canonical[key].add(cid)

        alias_rows = conn.execute("SELECT canonical_var_id, alias_text FROM variable_aliases").fetchall()
        for row in alias_rows:
            cid = str(row["canonical_var_id"] or "").strip()
            alias = str(row["alias_text"] or "").strip()
            if not cid or not alias:
                continue
            aliases_by_canonical[cid].append(alias)
            key = _lookup_key(alias)
            if key:
                alias_to_canonical[key].add(cid)

        normalized_aliases: dict[str, list[str]] = {}
        for cid, values in aliases_by_canonical.items():
            normalized_aliases[cid] = _dedupe_texts(values)
        return alias_to_canonical, normalized_aliases
