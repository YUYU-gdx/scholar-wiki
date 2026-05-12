from __future__ import annotations

from dataclasses import dataclass
import html
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid
from typing import Any

import requests

from kn_graph.providers.zhipu import ZhipuChatCompletionsClient
from kn_graph.services.mineru_runner import parse_single_pdf


_SENTENCE_END_RE = re.compile(r"[^。！？!?\.]+[。！？!?\.]?")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"(?i)<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.DOTALL)
    text = re.sub(r"(?i)</?(p|div|section|article|br|li|h[1-6]|tr|td|th|blockquote)[^>]*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if paragraphs:
        return paragraphs
    single_line = [line.strip() for line in text.splitlines() if line.strip()]
    return single_line


def _split_sentences(paragraph: str) -> list[str]:
    out: list[str] = []
    for match in _SENTENCE_END_RE.finditer(paragraph.strip()):
        sentence = match.group(0).strip()
        if sentence:
            out.append(sentence)
    return out


def _safe_segment(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    out: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch in {"_", "-", "."}:
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("._-")
    return re.sub(r"_+", "_", cleaned)


def _normalize_doi_for_key(doi: str) -> str:
    text = str(doi or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return _safe_segment(text)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_first_md_h1(md_text: str) -> str:
    for line in str(md_text or "").splitlines():
        text = line.strip()
        if text.startswith("# "):
            return text[2:].strip()
    return ""


def _extract_md_headings(md_text: str) -> list[tuple[int, str, int]]:
    headings: list[tuple[int, str, int]] = []
    for idx, line in enumerate(str(md_text or "").splitlines()):
        text = line.strip()
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", text)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        if title:
            headings.append((level, title, idx))
    return headings


def _is_abstract_heading(text: str) -> bool:
    normalized = re.sub(r"[\s\-_]+", "", str(text or "").strip().lower())
    return normalized in {"abstract", "summary", "摘要"}


def _paper_id_from_md(md_text: str, fallback: str) -> str:
    headings = _extract_md_headings(md_text)
    h1s = [(title, line_no) for level, title, line_no in headings if level == 1]
    if not h1s:
        return _safe_segment(fallback) or uuid.uuid4().hex

    chosen = h1s[0][0].strip()
    if len(h1s) >= 2:
        first_line = h1s[0][1]
        second_title, second_line = h1s[1]
        between = str(md_text or "").splitlines()[first_line + 1 : second_line]
        only_blank_between = all(not str(x).strip() for x in between)
        if only_blank_between:
            first_h2_under_second = ""
            for level, title, line_no in headings:
                if line_no <= second_line:
                    continue
                if level == 1:
                    break
                if level == 2:
                    first_h2_under_second = title
                    break
            if first_h2_under_second and not _is_abstract_heading(first_h2_under_second):
                chosen = second_title.strip()

    return _safe_segment(chosen) or _safe_segment(fallback) or uuid.uuid4().hex


def _safe_windows_filename(raw: str, fallback: str = "document") -> str:
    text = str(raw or "").strip()
    text = re.sub(r"[<>:\"/\\|?*]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip().strip(". ")
    if not text:
        text = fallback
    return text[:180]


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for i in range(1, 1000):
        cand = parent / f"{stem}_{i}{suffix}"
        if not cand.exists():
            return cand
    return parent / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def segment_html(paper_id: str, html: str, doi: str = "", title: str = "") -> dict[str, Any]:
    text = _strip_html(html)
    paragraphs = _split_paragraphs(text)
    sentence_rows: list[dict[str, Any]] = []
    paragraph_rows: list[dict[str, Any]] = []
    for p_idx, paragraph in enumerate(paragraphs, start=1):
        paragraph_id = f"p:{paper_id}:para:{p_idx}"
        sentences = _split_sentences(paragraph)
        if not sentences:
            sentences = [paragraph]
        sentence_ids: list[str] = []
        for s_idx, sentence in enumerate(sentences, start=1):
            sentence_id = f"s:{paper_id}:para:{p_idx}:sent:{s_idx}"
            sentence_ids.append(sentence_id)
            sentence_rows.append(
                {
                    "paper_id": paper_id,
                    "doi": doi,
                    "title": title,
                    "paragraph_id": paragraph_id,
                    "sentence_id": sentence_id,
                    "text": sentence,
                    "position": s_idx,
                }
            )
        paragraph_rows.append(
            {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "paragraph_id": paragraph_id,
                "text": paragraph,
                "sentence_ids": sentence_ids,
            }
        )
    return {
        "paper": {
            "paper_id": paper_id,
            "doi": doi,
            "title": title,
            "full_text": text,
            "metadata": {},
        },
        "paragraphs": paragraph_rows,
        "sentences": sentence_rows,
    }


def weighted_rrf_merge(
    keyword_hits: list[dict[str, Any]],
    rag_hits: list[dict[str, Any]],
    keyword_weight: float,
    rag_weight: float,
    k: int = 60,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(keyword_hits, start=1):
        hid = str(item.get("id", ""))
        if not hid:
            continue
        row = merged.setdefault(hid, {"id": hid})
        row.update({k2: v2 for k2, v2 in item.items() if k2 != "id"})
        row["keyword_rank"] = idx
        row["keyword_score"] = float(item.get("score", 0.0) or 0.0)
        row["keyword_rrf"] = float(keyword_weight) / float(k + idx)
    for idx, item in enumerate(rag_hits, start=1):
        hid = str(item.get("id", ""))
        if not hid:
            continue
        row = merged.setdefault(hid, {"id": hid})
        row.update({k2: v2 for k2, v2 in item.items() if k2 != "id"})
        row["rag_rank"] = idx
        row["rag_score"] = float(item.get("score", 0.0) or 0.0)
        row["rag_rrf"] = float(rag_weight) / float(k + idx)
    output = list(merged.values())
    for row in output:
        row["fused_score"] = round(float(row.get("keyword_rrf", 0.0) or 0.0) + float(row.get("rag_rrf", 0.0) or 0.0), 10)
    output.sort(key=lambda x: (-float(x.get("fused_score", 0.0)), str(x.get("id", ""))))
    return output


@dataclass(slots=True)
class OpenAICompatibleEmbeddingClient:
    api_key: str
    model: str = "embedding-3"
    endpoint_url: str = ""
    timeout_seconds: int = 120
    max_retries: int = 3
    max_chars: int = 8000
    batch_size: int = 32

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        max_chars = self.max_chars
        batch_size = max(1, self.batch_size)
        prepared = [str(t or "")[:max_chars] for t in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(prepared), batch_size):
            batch = prepared[i : i + batch_size]
            vectors.extend(self._embed_batch(batch))
        if len(vectors) != len(prepared):
            raise ValueError("embedding response length mismatch")
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = self.endpoint_url
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
                if resp.status_code == 400 and len(texts) > 1:
                    mid = len(texts) // 2
                    return self._embed_batch(texts[:mid]) + self._embed_batch(texts[mid:])
                if resp.status_code >= 500 and attempt < self.max_retries:
                    time.sleep(1.2 * attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                vectors: list[list[float]] = []
                for item in data.get("data", []):
                    embedding = item.get("embedding")
                    if isinstance(embedding, list):
                        vectors.append([float(v) for v in embedding])
                if len(vectors) != len(texts):
                    raise ValueError("embedding response length mismatch")
                return vectors
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.2 * attempt)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("embedding failed")


ZhipuEmbeddingClient = OpenAICompatibleEmbeddingClient  # backward compatibility


class _NoopEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class _NoopGeneratorClient:
    def complete(self, prompt: str, system_prompt: str = "") -> str:
        _ = prompt, system_prompt
        return "当前未配置文本生成模型，仅返回检索结果。"


def _scalar_meta(value: Any) -> str | int | float | bool | None:
    """Convert a property value to a ChromaDB-metadata-compatible scalar."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class ChromaDBClient:
    """Per-library embedded vector + keyword search backed by ChromaDB and SQLite FTS5."""

    _COLLECTION_NAMES = ("LiteratureSentence", "LiteratureParagraph", "LiteratureDocument")

    def __init__(self, persist_dir: str) -> None:
        import chromadb

        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        self._cdb = chromadb.PersistentClient(path=str(self._persist_dir))

        fts_path = str(self._persist_dir / "fts_index.db")
        self._fts = sqlite3.connect(fts_path, check_same_thread=False)
        self._fts.execute("PRAGMA journal_mode=WAL")
        self._fts.row_factory = sqlite3.Row
        self._fts_ready = False

        self._cols: dict[str, Any] = {}

    def close(self) -> None:
        """Release ChromaDB resources (file handles, SQLite connection)."""
        self._cols.clear()
        if hasattr(self, "_fts"):
            self._fts.close()
        # ChromaDB PersistentClient doesn't have an explicit close,
        # but clearing collections releases internal locks.

    def _get_col(self, class_name: str) -> Any:
        if class_name not in self._cols:
            self._cols[class_name] = self._cdb.get_or_create_collection(
                name=class_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._cols[class_name]

    def ensure_literature_schema(self) -> None:
        self._ensure_fts()
        for name in self._COLLECTION_NAMES:
            self._get_col(name)

    def _ensure_fts(self) -> None:
        if self._fts_ready:
            return
        for name in self._COLLECTION_NAMES:
            self._fts.execute(
                f"CREATE TABLE IF NOT EXISTS {name}_fts("
                f"  object_id TEXT PRIMARY KEY,"
                f"  paper_id TEXT,"
                f"  title TEXT,"
                f"  text TEXT"
                f")"
            )
            self._fts.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {name}_fts_idx"
                f" USING fts5(object_id, paper_id, title, text,"
                f"  content={name}_fts, content_rowid='rowid',"
                f"  tokenize='unicode61 remove_diacritics 2')"
            )
            # Triggers to keep FTS index in sync with content table
            self._fts.execute(
                f"CREATE TRIGGER IF NOT EXISTS {name}_fts_ai AFTER INSERT ON {name}_fts BEGIN\n"
                f"  INSERT INTO {name}_fts_idx(rowid, object_id, paper_id, title, text)\n"
                f"  VALUES (NEW.rowid, NEW.object_id, NEW.paper_id, NEW.title, NEW.text);\n"
                f"END"
            )
            self._fts.execute(
                f"CREATE TRIGGER IF NOT EXISTS {name}_fts_ad AFTER DELETE ON {name}_fts BEGIN\n"
                f"  INSERT INTO {name}_fts_idx({name}_fts_idx, rowid, object_id, paper_id, title, text)\n"
                f"  VALUES ('delete', OLD.rowid, OLD.object_id, OLD.paper_id, OLD.title, OLD.text);\n"
                f"END"
            )
            self._fts.execute(
                f"CREATE TRIGGER IF NOT EXISTS {name}_fts_au AFTER UPDATE ON {name}_fts BEGIN\n"
                f"  INSERT INTO {name}_fts_idx({name}_fts_idx, rowid, object_id, paper_id, title, text)\n"
                f"  VALUES ('delete', OLD.rowid, OLD.object_id, OLD.paper_id, OLD.title, OLD.text);\n"
                f"  INSERT INTO {name}_fts_idx(rowid, object_id, paper_id, title, text)\n"
                f"  VALUES (NEW.rowid, NEW.object_id, NEW.paper_id, NEW.title, NEW.text);\n"
                f"END"
            )
        self._fts.commit()
        self._fts_ready = True

    def upsert(self, class_name: str, object_id: str, properties: dict[str, Any], vector: list[float]) -> None:
        col = self._get_col(class_name)
        meta = {k: _scalar_meta(v) for k, v in properties.items() if _scalar_meta(v) is not None}
        doc_text = str(properties.get("text") or properties.get("full_text") or "")
        col.upsert(
            ids=[object_id],
            embeddings=[vector],
            metadatas=[meta],
            documents=[doc_text],
        )
        self._ensure_fts()
        self._fts.execute(
            f"INSERT OR REPLACE INTO {class_name}_fts(object_id, paper_id, title, text) VALUES (?, ?, ?, ?)",
            (
                object_id,
                str(properties.get("paper_id", "")),
                str(properties.get("title", "")),
                doc_text,
            ),
        )
        self._fts.commit()

    def upsert_many(self, class_name: str, rows: list[tuple[str, dict[str, Any], list[float]]]) -> None:
        if not rows:
            return
        col = self._get_col(class_name)
        ids: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []
        documents: list[str] = []
        fts_rows: list[tuple[str, str, str, str]] = []
        for object_id, properties, vector in rows:
            meta = {k: _scalar_meta(v) for k, v in properties.items() if _scalar_meta(v) is not None}
            doc_text = str(properties.get("text") or properties.get("full_text") or "")
            ids.append(object_id)
            embeddings.append(vector)
            metadatas.append(meta)
            documents.append(doc_text)
            fts_rows.append(
                (
                    str(object_id),
                    str(properties.get("paper_id", "")),
                    str(properties.get("title", "")),
                    doc_text,
                )
            )
        col.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )
        self._ensure_fts()
        self._fts.executemany(
            f"INSERT OR REPLACE INTO {class_name}_fts(object_id, paper_id, title, text) VALUES (?, ?, ?, ?)",
            fts_rows,
        )
        self._fts.commit()

    def bm25_search(self, class_name: str, query: str, limit: int, library_id: str = "") -> list[dict[str, Any]]:
        self._ensure_fts()
        escaped = query.replace('"', '""')
        try:
            rows = self._fts.execute(
                f"SELECT object_id, paper_id, title, text, rank"
                f" FROM {class_name}_fts_idx"
                f" WHERE {class_name}_fts_idx MATCH ?"
                f" ORDER BY rank"
                f" LIMIT ?",
                (f'text:"{escaped}"', int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            # Convert FTS5 rank to a 0-1 score (FTS5 rank is negative, higher is better)
            rank = float(d.get("rank", 0.0) or 0.0)
            score = 1.0 / (1.0 + abs(rank)) if rank < 0 else 1.0
            out.append(
                {
                    "id": str(d.get("object_id", "")),
                    "score": score,
                    "properties": {
                        "paper_id": str(d.get("paper_id", "")),
                        "title": str(d.get("title", "")),
                        "text": str(d.get("text", "")),
                    },
                }
            )
        return out

    def vector_search(self, class_name: str, vector: list[float], limit: int, library_id: str = "") -> list[dict[str, Any]]:
        col = self._get_col(class_name)
        results = col.query(query_embeddings=[vector], n_results=int(limit), include=["metadatas", "distances"])
        out: list[dict[str, Any]] = []
        ids_list = results.get("ids", [[]])
        distances_list = results.get("distances", [[]])
        metadatas_list = results.get("metadatas", [[]])
        ids = ids_list[0] if ids_list else []
        distances = distances_list[0] if distances_list else []
        metadatas = metadatas_list[0] if metadatas_list else []
        for obj_id, dist, meta in zip(ids, distances, metadatas):
            props = dict(meta or {})
            if isinstance(dist, (int, float)):
                score = 1.0 / (1.0 + float(dist))
            else:
                score = 0.0
            out.append(
                {
                    "id": str(obj_id or ""),
                    "score": score,
                    "properties": props,
                }
            )
        return out


# Module-level cache: share ChromaDBClient instances across all LiteratureService
# instances to prevent concurrent PersistentClient conflicts on the same directory.
# Keyed by (thread_id, library_id) to avoid cross-thread SQLite errors.
_chroma_client_cache: dict[str, ChromaDBClient] = {}
_chroma_client_lock = threading.Lock()


def _chroma_cache_key(library_id: str) -> str:
    return f"{threading.get_ident()}:{library_id}"


class LiteratureService:
    def __init__(
        self,
        settings: Any = None,
        embedding_client: Any | None = None,
        generator_client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._chroma_clients: dict[str, ChromaDBClient] = {}
        if embedding_client is not None:
            self.embedding = embedding_client
        else:
            try:
                self.embedding = self._build_default_embedding()
            except Exception:
                self.embedding = _NoopEmbeddingClient()
        if generator_client is not None:
            self.generator = generator_client
        else:
            try:
                self.generator = self._build_default_generator()
            except Exception:
                self.generator = _NoopGeneratorClient()
        self._sentence_by_id: dict[str, dict[str, Any]] = {}
        self._paragraph_by_id: dict[str, dict[str, Any]] = {}
        self._document_by_id: dict[str, dict[str, Any]] = {}
        self._workspace_root_cache: dict[str, Path] = {}

    def _ensure_service(self) -> LiteratureService:
        """Backward compatibility with old wrapper pattern. Returns self."""
        return self

    def _normalize_storage_path(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.replace("\\", "/")

    def _default_library_id(self) -> str:
        if self._settings is None:
            return ""
        return (self._settings.literature_default_library_id or "").strip()

    def _library_index_root(self) -> Path:
        if self._settings is None:
            return Path("outputs/literature_libraries")
        return Path(self._settings.indexes_dir)

    def _library_index_path(self, library_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(library_id or "").strip())
        return self._library_index_root() / f"{safe}.json"

    def _load_library_paper_ids(self, library_id: str) -> set[str]:
        lib = str(library_id or "").strip()
        if not lib:
            return set()
        path = self._library_index_path(lib)
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        ids = payload.get("paper_ids", []) if isinstance(payload, dict) else []
        return {str(x).strip() for x in ids if str(x).strip()}

    def _update_library_index(self, library_id: str, paper_ids: list[str]) -> None:
        lib = str(library_id or "").strip()
        if not lib:
            return
        cleaned = [str(x).strip() for x in paper_ids if str(x).strip()]
        if not cleaned:
            return
        path = self._library_index_path(lib)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = self._load_library_paper_ids(lib)
        merged.update(cleaned)
        payload = {
            "library_id": lib,
            "paper_count": len(merged),
            "paper_ids": sorted(merged),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _resolve_workspace_root(self, library_id: str) -> Path | None:
        lib = str(library_id or "").strip()
        if not lib:
            return None
        cached = self._workspace_root_cache.get(lib)
        if cached is not None:
            return cached
        root = self._settings.workspaces_dir / lib
        if not root.exists() or not root.is_dir():
            return None
        path = Path(root).resolve()
        self._workspace_root_cache[lib] = path
        return path

    def _iter_workspace_libraries(self) -> list[tuple[str, Path]]:
        root = Path(self._settings.workspaces_dir).resolve()
        if not root.exists() or not root.is_dir():
            return []
        rows: list[tuple[str, Path]] = []
        for item in sorted(root.iterdir(), key=lambda p: p.name):
            if not item.is_dir():
                continue
            name = str(item.name or "").strip()
            if not name or name.startswith("."):
                continue
            rows.append((name, item.resolve()))
        return rows

    @staticmethod
    def _count_papers_in_workspace(workspace_root: Path) -> int:
        db_path = workspace_root / "kn_gragh.db"
        if not db_path.exists() or not db_path.is_file():
            return 0
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("select count(*) from papers")
            count = int(cur.fetchone()[0])
            conn.close()
            return max(0, count)
        except Exception:
            return 0

    def _paper_key_for_row(self, row: dict[str, Any], source_path: Path | None, html_text: str) -> str:
        doi_norm = _normalize_doi_for_key(str(row.get("doi", "") or ""))
        if doi_norm and not doi_norm.startswith("job_"):
            return f"doi_{doi_norm}"
        title = str(row.get("title", "") or "").strip()
        if title:
            title_key = _safe_segment(title)
            if title_key and title_key not in {"job", "item", "paper", "article"}:
                return f"title_{title_key[:160]}"
        if doi_norm:
            return f"doi_{doi_norm}"
        if source_path is not None and source_path.exists() and source_path.is_file():
            digest = _sha256_file(source_path)
        else:
            digest = hashlib.sha256(str(html_text or "").encode("utf-8", errors="ignore")).hexdigest()
        return f"hash_{digest[:16]}"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update_workspace_paper_index(self, workspace_root: Path, row: dict[str, Any]) -> None:
        index_path = workspace_root / "corpus" / "index" / "papers.ndjson"
        existing: dict[str, dict[str, Any]] = {}
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                text = line.strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                key = str(obj.get("paper_key", "") or "").strip()
                if key:
                    existing[key] = obj
        key = str(row.get("paper_key", "") or "").strip()
        if key:
            existing[key] = dict(row)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("w", encoding="utf-8", newline="\n") as f:
            for paper_key in sorted(existing.keys()):
                f.write(json.dumps(existing[paper_key], ensure_ascii=False) + "\n")

    def _materialize_workspace_assets(
        self,
        library_id: str,
        row: dict[str, Any],
        source_path: Path | None,
        html_inline: str,
    ) -> dict[str, Any]:
        workspace_root = self._resolve_workspace_root(library_id)
        if workspace_root is None:
            return {"html_text": html_inline or self._normalize_to_html(source_path), "source_html": str(source_path or ""), "materialized": None}

        html_seed = str(html_inline or "")
        paper_key = self._paper_key_for_row(row=row, source_path=source_path, html_text=html_seed)
        paper_root = workspace_root / "corpus" / "papers" / paper_key
        source_dir = paper_root / "source"
        html_dir = paper_root / "derived" / "html"
        mineru_latest_dir = paper_root / "derived" / "mineru" / "latest"
        meta_path = paper_root / "meta" / "paper.json"
        source_dir.mkdir(parents=True, exist_ok=True)
        html_dir.mkdir(parents=True, exist_ok=True)
        (paper_root / "meta").mkdir(parents=True, exist_ok=True)

        source_pdf_path = ""
        source_md_path = ""
        mineru_main_md_path = ""
        md_library_path = ""
        parser_name = ""
        parser_version = ""
        parser_run_at = ""
        html_text = ""

        ext = source_path.suffix.lower() if isinstance(source_path, Path) else ""
        title_candidate = str(row.get("title", "") or "").strip()
        if isinstance(source_path, Path) and source_path.exists() and source_path.is_file() and ext == ".pdf":
            source_pdf = source_dir / _safe_windows_filename(source_path.name, fallback="original.pdf")
            shutil.copy2(str(source_path), str(source_pdf))
            source_pdf_path = str(source_pdf.resolve())
            parser_name = "mineru"
            parser_version = str(self._settings.mineru_version or "").strip() or "unknown"
            parser_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            preparsed_dir_raw = str(row.get("preparsed_mineru_dir", "") or "").strip()
            preparsed_md_raw = str(row.get("preparsed_main_md_path", "") or "").strip()
            preparsed_html_raw = str(row.get("preparsed_html_path", "") or "").strip()
            preparsed_dir = Path(preparsed_dir_raw) if preparsed_dir_raw else None
            preparsed_md = Path(preparsed_md_raw) if preparsed_md_raw else None
            preparsed_html = Path(preparsed_html_raw) if preparsed_html_raw else None

            if not (isinstance(preparsed_dir, Path) and preparsed_dir.exists() and preparsed_dir.is_dir()):
                raise RuntimeError("missing_preparsed_mineru_output_for_pdf_import")
            if mineru_latest_dir.exists():
                shutil.rmtree(mineru_latest_dir, ignore_errors=True)
            shutil.copytree(preparsed_dir, mineru_latest_dir, dirs_exist_ok=True)
            md_candidates = sorted(mineru_latest_dir.rglob("*.md"))
            chosen_md: Path | None = None
            if isinstance(preparsed_md, Path) and preparsed_md.exists() and preparsed_md.is_file():
                for cand in md_candidates:
                    if cand.name == preparsed_md.name:
                        chosen_md = cand
                        break
            if chosen_md is None and md_candidates:
                preferred = [x for x in md_candidates if x.name.lower() not in {"full.md", "merged.md", "output.md"}]
                chosen_md = preferred[0] if preferred else md_candidates[0]
            if chosen_md is None or not chosen_md.exists():
                raise RuntimeError("missing_markdown_in_preparsed_mineru_output")

            chosen_text = chosen_md.read_text(encoding="utf-8", errors="ignore")
            chosen_h1 = _extract_first_md_h1(chosen_text)
            new_name = _safe_windows_filename(chosen_h1 or title_candidate or chosen_md.stem, fallback=chosen_md.stem) + ".md"
            target_md = _dedupe_path(mineru_latest_dir / new_name)
            if chosen_md.resolve() != target_md.resolve():
                chosen_md.rename(target_md)
            mineru_main_md_path = str(target_md.resolve())
            source_md_path = mineru_main_md_path
            for leftover in sorted(mineru_latest_dir.rglob("*.md")):
                if leftover.resolve() != target_md.resolve():
                    leftover.unlink(missing_ok=True)
            md_library_path = str(mineru_latest_dir.resolve())
            if isinstance(preparsed_html, Path) and preparsed_html.exists() and preparsed_html.is_file():
                html_text = preparsed_html.read_text(encoding="utf-8", errors="ignore")
            else:
                md_text = Path(mineru_main_md_path).read_text(encoding="utf-8", errors="ignore")
                html_text = f"<html><body><pre>{html.escape(md_text)}</pre></body></html>"
        elif isinstance(source_path, Path) and source_path.exists() and source_path.is_file() and ext == ".md":
            md_raw = source_path.read_text(encoding="utf-8", errors="ignore")
            md_h1 = _extract_first_md_h1(md_raw)
            if md_h1:
                title_candidate = md_h1
            md_name = _safe_windows_filename(md_h1 or source_path.stem, fallback=source_path.stem) + ".md"
            md_target = source_dir / md_name
            shutil.copy2(str(source_path), str(md_target))
            source_md_path = str(md_target.resolve())
            html_text = f"<html><body><pre>{html.escape(md_raw)}</pre></body></html>"
            if mineru_latest_dir.exists():
                shutil.rmtree(mineru_latest_dir, ignore_errors=True)
        elif html_seed:
            html_text = html_seed
            if mineru_latest_dir.exists():
                shutil.rmtree(mineru_latest_dir, ignore_errors=True)
        else:
            html_text = self._normalize_to_html(source_path)
            if mineru_latest_dir.exists():
                shutil.rmtree(mineru_latest_dir, ignore_errors=True)

        html_basename = _safe_windows_filename(title_candidate or str(row.get("paper_id", "") or "article"), fallback="article")
        article_html_path = html_dir / f"{html_basename}.html"
        article_html_path.write_text(html_text, encoding="utf-8")

        source_hash = ""
        source_size = 0
        if isinstance(source_path, Path) and source_path.exists() and source_path.is_file():
            source_hash = _sha256_file(source_path)
            try:
                source_size = int(source_path.stat().st_size)
            except Exception:
                source_size = 0
        else:
            source_hash = hashlib.sha256(html_text.encode("utf-8", errors="ignore")).hexdigest()

        metadata_payload = {
            "paper_key": paper_key,
            "library_id": str(library_id or "").strip(),
            "paper_id": str(row.get("paper_id", "") or "").strip(),
            "doi": str(row.get("doi", "") or "").strip(),
            "title": title_candidate or str(row.get("title", "") or "").strip(),
            "import_source_path": str(source_path.resolve()) if isinstance(source_path, Path) and source_path.exists() else "",
            "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_pdf_path": source_pdf_path,
            "source_md_path": source_md_path,
            "html_path": str(article_html_path.resolve()),
            "mineru_output_path": str(mineru_latest_dir.resolve()) if mineru_latest_dir.exists() else "",
            "mineru_main_md_path": mineru_main_md_path,
            "md_library_path": md_library_path,
            "content_hash": source_hash,
            "file_size": source_size,
            "parser": {
                "name": parser_name,
                "version": parser_version,
                "run_at": parser_run_at,
            },
        }
        self._write_json(meta_path, metadata_payload)
        self._update_workspace_paper_index(
            workspace_root,
            {
                "paper_key": paper_key,
                "library_id": str(library_id or "").strip(),
                "paper_id": str(row.get("paper_id", "") or "").strip(),
                "doi": str(row.get("doi", "") or "").strip(),
                "title": title_candidate or str(row.get("title", "") or "").strip(),
                "source_pdf_path": source_pdf_path,
                "source_md_path": source_md_path,
                "html_path": str(article_html_path.resolve()),
                "mineru_output_path": str(mineru_latest_dir.resolve()) if mineru_latest_dir.exists() else "",
                "mineru_main_md_path": mineru_main_md_path,
                "md_library_path": md_library_path,
                "updated_at": metadata_payload["imported_at"],
            },
        )
        return {
            "html_text": html_text,
            "source_html": str(article_html_path.resolve()),
            "workspace_path": str(workspace_root.resolve()),
            "materialized": {
                "paper_key": paper_key,
                "source_pdf_path": source_pdf_path,
                "html_path": str(article_html_path.resolve()),
                "mineru_output_path": str(mineru_latest_dir.resolve()) if mineru_latest_dir.exists() else "",
                "mineru_main_md_path": mineru_main_md_path,
                "md_library_path": md_library_path,
                "meta_path": str(meta_path.resolve()),
            },
        }

    def _get_chroma(self, library_id: str) -> ChromaDBClient:
        lib = str(library_id or "").strip()
        if not lib:
            raise RuntimeError("library_id_required")
        # Fast path: instance cache
        if lib in self._chroma_clients:
            return self._chroma_clients[lib]
        # Thread-safe module-level cache keyed by (thread, library) to avoid
        # "SQLite objects created in a thread can only be used in that same thread"
        with _chroma_client_lock:
            ck = _chroma_cache_key(lib)
            if ck in _chroma_client_cache:
                client = _chroma_client_cache[ck]
            else:
                workspace = self._resolve_workspace_root(lib)
                if workspace is None:
                    raise RuntimeError(f"workspace_not_found:{lib}")
                chroma_dir = workspace / "chromadb"
                client = ChromaDBClient(str(chroma_dir))
                _chroma_client_cache[ck] = client
        self._chroma_clients[lib] = client
        return client

    def _build_default_embedding(self) -> OpenAICompatibleEmbeddingClient:
        provider = (getattr(self._settings, "embedding_provider", "") or "").strip() or "zhipu"
        api_key = (getattr(self._settings, "embedding_api_key", "") or "").strip()
        # Fallback to legacy zhipu_api_key for existing installs
        if not api_key:
            api_key = (getattr(self._settings, "zhipu_api_key", "") or "").strip()
        model = (getattr(self._settings, "embedding_model", "") or "").strip()
        if not model:
            model = self._settings.literature_embedding_model.strip() or "embedding-3"
        endpoint_url = (getattr(self._settings, "embedding_endpoint_url", "") or "").strip()
        if not endpoint_url:
            endpoint_url = "https://open.bigmodel.cn/api/paas/v4/embeddings"
        if not api_key:
            raise RuntimeError("missing embedding api_key: configure an embedding provider in Settings")
        return OpenAICompatibleEmbeddingClient(
            api_key=api_key,
            model=model,
            endpoint_url=endpoint_url,
            max_chars=self._settings.literature_embed_max_chars,
            batch_size=self._settings.literature_embed_batch_size,
        )

    def _build_default_generator(self) -> Any:
        api_key = self._settings.zhipu_api_key.strip()
        if not api_key:
            raise RuntimeError("missing env: ZHIPU_API_KEY")
        model = self._settings.literature_chat_model.strip() or "glm-4.5-flash"
        return ZhipuChatCompletionsClient(api_key=api_key, model=model)

    # ------------------------------------------------------------------
    # Library CRUD (pure filesystem operations)
    # ------------------------------------------------------------------

    def list_libraries(self) -> dict[str, Any]:
        workspaces_root = Path(self._settings.workspaces_dir).resolve()
        indexes_root = Path(self._settings.indexes_dir).resolve()
        libraries: dict[str, dict[str, Any]] = {}

        if workspaces_root.exists() and workspaces_root.is_dir():
            for item in sorted(workspaces_root.iterdir(), key=lambda p: p.name.lower()):
                if not item.is_dir():
                    continue
                lib = str(item.name or "").strip()
                if not lib or lib.startswith("."):
                    continue
                libraries[lib] = {
                    "library_id": lib,
                    "paper_count": self._count_papers_in_workspace(item.resolve()),
                    "updated_at": "",
                    "path": str((indexes_root / f"{lib}.json").resolve()),
                    "workspace_path": str(item.resolve()),
                }

        if indexes_root.exists() and indexes_root.is_dir():
            for fp in sorted(indexes_root.glob("*.json"), key=lambda p: p.name.lower()):
                lib = str(fp.stem or "").strip()
                if not lib:
                    continue
                paper_count = 0
                updated_at = ""
                try:
                    payload = json.loads(fp.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        paper_count = max(0, int(payload.get("paper_count", 0) or 0))
                        updated_at = str(payload.get("updated_at", "") or "").strip()
                except Exception:
                    pass
                row = libraries.get(lib)
                if row is None:
                    ws = (workspaces_root / lib).resolve()
                    libraries[lib] = {
                        "library_id": lib,
                        "paper_count": paper_count,
                        "updated_at": updated_at,
                        "path": str(fp.resolve()),
                        "workspace_path": str(ws),
                    }
                else:
                    if row.get("paper_count", 0) <= 0 and paper_count > 0:
                        row["paper_count"] = paper_count
                    if not str(row.get("updated_at", "") or "").strip() and updated_at:
                        row["updated_at"] = updated_at
                    row["path"] = str(fp.resolve())

        rows = sorted(libraries.values(), key=lambda x: str(x.get("library_id", "")).lower())
        default_library_id = rows[0]["library_id"] if rows else ""
        return {"libraries": rows, "default_library_id": default_library_id}

    def create_library(self, library_id: str, workspace_root: str = "", set_default: bool = True) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if str(workspace_root or "").strip():
            ws = Path(workspace_root).resolve()
        else:
            ws = (Path(self._settings.workspaces_dir).resolve() / lib).resolve()
        ws.mkdir(parents=True, exist_ok=True)

        index_path = (Path(self._settings.indexes_dir).resolve() / f"{lib}.json").resolve()
        index_path.parent.mkdir(parents=True, exist_ok=True)
        if not index_path.exists():
            payload = {
                "library_id": lib,
                "paper_count": 0,
                "paper_ids": [],
                "workspace_root": str(ws),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "library_id": lib,
            "workspace_path": str(ws),
            "index_path": str(index_path),
            "default_library_id": lib if set_default else "",
        }

    def delete_library(self, library_id: str, delete_workspace_data: bool = True) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        ws = (Path(self._settings.workspaces_dir).resolve() / lib).resolve()
        index_path = (Path(self._settings.indexes_dir).resolve() / f"{lib}.json").resolve()

        deleted_workspace = False
        deleted_workspace_paths: list[str] = []
        if bool(delete_workspace_data) and ws.exists() and ws.is_dir():
            client = self._chroma_clients.pop(lib, None)
            if client is not None:
                client.close()
            shutil.rmtree(ws)
            deleted_workspace = True
            deleted_workspace_paths.append(str(ws))

        if index_path.exists() and index_path.is_file():
            index_path.unlink(missing_ok=True)

        deleted = not ws.exists() and not index_path.exists()
        return {
            "library_id": lib,
            "deleted": bool(deleted),
            "deleted_workspace": deleted_workspace,
            "deleted_workspace_paths": deleted_workspace_paths,
            "workspace_path": str(ws),
            "index_path": str(index_path),
            "default_library_id": "",
        }

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def import_manifest(self, manifest_path: Path | str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options if isinstance(options, dict) else {}
        library_id = str(options.get("library_id", "") or self._default_library_id()).strip()
        index_mode = str(options.get("index_mode", "parent_child") or "parent_child").strip().lower()
        if index_mode not in {"parent_child", "legacy"}:
            index_mode = "parent_child"
        upsert_batch_size = max(1, int(options.get("upsert_batch_size", 200) or 200))
        path = Path(manifest_path)
        rows = _iter_jsonl(path)
        self._get_chroma(library_id).ensure_literature_schema()
        imported = 0
        sent_count = 0
        para_count = 0
        doc_count = 0
        imported_paper_ids: list[str] = []
        materialized_rows: list[dict[str, Any]] = []
        workspace_path = ""
        for row in rows:
            result = self._import_row(
                row,
                library_id=library_id,
                index_mode=index_mode,
                upsert_batch_size=upsert_batch_size,
            )
            imported += 1
            imported_paper_ids.append(str(result.get("paper_id", "") or row.get("paper_id") or row.get("doi") or "").strip())
            sent_count += int(result["sentence_count"])
            para_count += int(result["paragraph_count"])
            doc_count += int(result["document_count"])
            ws = str(result.get("workspace_path", "") or "").strip()
            if ws and not workspace_path:
                workspace_path = ws
            mat = result.get("materialized")
            if isinstance(mat, dict) and mat:
                materialized_rows.append(mat)
        self._update_library_index(library_id, imported_paper_ids)
        result = {
            "manifest_path": str(path),
            "library_id": library_id,
            "imported_count": imported,
            "sentence_count": sent_count,
            "paragraph_count": para_count,
            "document_count": doc_count,
            "workspace_path": workspace_path,
            "materialized_papers": materialized_rows,
            "index_mode": index_mode,
            "upsert_batch_size": upsert_batch_size,
        }
        ws_path = str(result.get("workspace_path", "") or "").strip()
        if ws_path:
            try:
                from kn_graph.services.agent_workspace_guard import ensure_agent_workspace_minimal_config
                ensure_agent_workspace_minimal_config(
                    ws_path,
                    "pipeline_library",
                    library_id=library_id,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "import_manifest: failed to sync workspace minimal agent config",
                    exc_info=True,
                )
        return result

    def _import_row(
        self,
        row: dict[str, Any],
        library_id: str = "",
        index_mode: str = "parent_child",
        upsert_batch_size: int = 200,
    ) -> dict[str, Any]:
        library_id = str(library_id or row.get("library_id", "") or self._default_library_id()).strip()
        doi = str(row.get("doi", "") or "").strip()
        title = str(row.get("title", "") or "").strip()
        source_path = self._resolve_source_path(row)
        html_text = str(row.get("html", "") or "").strip()
        md_text_for_id = ""
        if isinstance(source_path, Path) and source_path.exists() and source_path.is_file() and source_path.suffix.lower() == ".md":
            md_text_for_id = source_path.read_text(encoding="utf-8", errors="ignore")
        elif html_text:
            m = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", html_text)
            if m:
                md_text_for_id = html.unescape(m.group(1))
        if md_text_for_id.strip():
            paper_id = _paper_id_from_md(md_text_for_id, fallback=doi or title or str(row.get("paper_id", "") or "paper"))
        else:
            paper_id = str(row.get("paper_id") or row.get("doi") or uuid.uuid4().hex).strip()
        row_for_import = dict(row)
        row_for_import["paper_id"] = paper_id
        if not title and md_text_for_id.strip():
            md_h1 = _extract_first_md_h1(md_text_for_id)
            if md_h1:
                title = md_h1
                row_for_import["title"] = md_h1
        materialized = self._materialize_workspace_assets(
            library_id=library_id,
            row=row_for_import,
            source_path=source_path,
            html_inline=html_text,
        )
        html_text = str(materialized.get("html_text", "") or html_text)
        source_html = str(materialized.get("source_html", "") or (str(source_path) if source_path else ""))
        if not html_text:
            html_text = self._normalize_to_html(source_path)

        segmented = segment_html(paper_id=paper_id, html=html_text, doi=doi, title=title)
        sentences = segmented["sentences"]
        paragraphs = segmented["paragraphs"]
        paper = dict(segmented["paper"])
        paper["source_html"] = source_html
        paper["metadata"] = {
            k: v
            for k, v in row_for_import.items()
            if k not in {"html"}
        }
        mat_payload = materialized.get("materialized") if isinstance(materialized, dict) else None
        if isinstance(mat_payload, dict) and mat_payload:
            paper["metadata"]["paper_key"] = str(mat_payload.get("paper_key", "") or "")

        sentence_vectors = self.embedding.embed_texts([str(s.get("text", "")) for s in sentences])
        paragraph_vectors: list[list[float]] = []
        document_vectors: list[list[float]] = []
        if index_mode == "legacy":
            paragraph_vectors = self.embedding.embed_texts([str(p.get("text", "")) for p in paragraphs])
            document_vectors = self.embedding.embed_texts([str(paper.get("full_text", ""))])

        chroma = self._get_chroma(library_id)
        sentence_rows: list[tuple[str, dict[str, Any], list[float]]] = []
        for sentence, vector in zip(sentences, sentence_vectors):
            sid = str(sentence["sentence_id"])
            sentence["library_id"] = library_id
            sentence["source_html"] = paper["source_html"]
            sentence["parent_id"] = str(sentence.get("paragraph_id", ""))
            self._sentence_by_id[f"{library_id}::{sid}"] = dict(sentence)
            object_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"LiteratureSentence:{library_id}:{paper_id}:{sid}"))
            sentence_rows.append((object_id, sentence, vector))
        for i in range(0, len(sentence_rows), upsert_batch_size):
            chroma.upsert_many("LiteratureSentence", sentence_rows[i : i + upsert_batch_size])

        paragraph_rows: list[tuple[str, dict[str, Any], list[float]]] = []
        for idx, paragraph in enumerate(paragraphs):
            pid = str(paragraph["paragraph_id"])
            paragraph["library_id"] = library_id
            paragraph["source_html"] = paper["source_html"]
            paragraph["parent_id"] = paper_id
            self._paragraph_by_id[f"{library_id}::{pid}"] = dict(paragraph)
            if index_mode == "legacy":
                object_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"LiteratureParagraph:{library_id}:{paper_id}:{pid}"))
                paragraph_rows.append((object_id, paragraph, paragraph_vectors[idx]))
        for i in range(0, len(paragraph_rows), upsert_batch_size):
            chroma.upsert_many("LiteratureParagraph", paragraph_rows[i : i + upsert_batch_size])

        self._document_by_id[f"{library_id}::{paper_id}"] = dict(paper)
        if index_mode == "legacy" and document_vectors:
            object_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"LiteratureDocument:{library_id}:{paper_id}"))
            chroma.upsert(
                "LiteratureDocument",
                object_id,
                {
                    "library_id": library_id,
                    "paper_id": paper_id,
                    "doi": paper.get("doi", ""),
                    "title": paper.get("title", ""),
                    "full_text": paper.get("full_text", ""),
                    "source_html": paper.get("source_html", ""),
                    "metadata_json": json.dumps(paper.get("metadata", {}), ensure_ascii=False),
                },
                document_vectors[0],
            )
        return {
            "paper_id": paper_id,
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "document_count": 1 if index_mode == "legacy" else 0,
            "workspace_path": str(materialized.get("workspace_path", "") or ""),
            "materialized": mat_payload if isinstance(mat_payload, dict) else {},
        }

    def _resolve_source_path(self, row: dict[str, Any]) -> Path | None:
        for key in ("source_path", "offline_html_path", "raw_html_path", "html_path", "full_html_path", "file_path"):
            val = str(row.get(key, "") or "").strip()
            if val:
                return Path(val)
        return None

    def _normalize_to_html(self, source_path: Path | None) -> str:
        if source_path is None:
            return "<html><body></body></html>"
        ext = source_path.suffix.lower()
        if ext == ".pdf":
            return self._pdf_to_html_cloud(source_path)
        raw = source_path.read_text(encoding="utf-8", errors="ignore")
        if ext in {".html", ".htm"}:
            return raw
        escaped = html.escape(raw)
        return f"<html><body><pre>{escaped}</pre></body></html>"

    def _pdf_to_html_cloud(self, source_pdf: Path) -> str:
        """Convert a PDF to HTML using the Mineru cloud API (fallback path
        used when no workspace root is available)."""
        with tempfile.TemporaryDirectory(prefix="mineru_cloud_normalize_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = parse_single_pdf(source_pdf, tmp_path, options={})
            return Path(str(result.get("html_path", "") or "")).read_text(encoding="utf-8", errors="ignore")

    def search(
        self,
        query: str,
        top_k: int = 20,
        levels: list[str] | None = None,
        library_id: str = "",
        keyword_weight: float = 0.4,
        rag_weight: float = 0.6,
        include_expanded_context: bool = True,
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        levels = levels or ["sentence"]
        top_k = max(1, int(top_k))
        query_vecs = self.embedding.embed_texts([query])
        query_vec = query_vecs[0] if query_vecs else []
        keyword_hits: list[dict[str, Any]] = []
        rag_hits: list[dict[str, Any]] = []
        degraded_routes: list[str] = []
        lib = str(library_id or "").strip()
        chroma = self._get_chroma(lib)
        fetch_limit = top_k
        for level in levels:
            class_name = _level_to_class(level)
            try:
                kw_rows = chroma.bm25_search(class_name, query=query, limit=fetch_limit)
            except Exception as exc:  # noqa: BLE001
                kw_rows = []
                degraded_routes.append(f"{level}:keyword:{exc}")
            vg_rows: list[dict[str, Any]] = []
            if isinstance(query_vec, list) and len(query_vec) > 0:
                try:
                    vg_rows = chroma.vector_search(class_name, vector=query_vec, limit=fetch_limit)
                except Exception as exc:  # noqa: BLE001
                    vg_rows = []
                    degraded_routes.append(f"{level}:vector:{exc}")
            for row in kw_rows:
                keyword_hits.append(self._format_hit(level, row, route="keyword", include_context=include_expanded_context, forced_library_id=lib))
            for row in vg_rows:
                rag_hits.append(self._format_hit(level, row, route="rag", include_context=include_expanded_context, forced_library_id=lib))
        merged_hits = weighted_rrf_merge(keyword_hits, rag_hits, keyword_weight=keyword_weight, rag_weight=rag_weight)
        return {
            "query": query,
            "library_id": lib,
            "keyword_hits": keyword_hits[:top_k],
            "rag_hits": rag_hits[:top_k],
            "merged_hits": merged_hits[:top_k],
            "search_meta": {
                "keyword_weight": float(keyword_weight),
                "rag_weight": float(rag_weight),
                "levels": levels,
                "library_id": lib,
                "library_filter_applied": True,
                "library_filter_mode": "per_library_chromadb",
                "library_registry_paper_count": 0,
                "degraded": bool(degraded_routes),
                "degraded_routes": degraded_routes,
            },
        }

    def _format_hit(
        self,
        level: str,
        row: dict[str, Any],
        route: str,
        include_context: bool,
        forced_library_id: str = "",
    ) -> dict[str, Any]:
        props = row.get("properties", {}) if isinstance(row.get("properties"), dict) else {}
        hid = str(row.get("id", "") or "")
        lib = str(props.get("library_id", "") or forced_library_id or "")
        hit = {
            "id": f"{level}:{hid}",
            "route": route,
            "level": level,
            "score": float(row.get("score", 0.0) or 0.0),
            "library_id": lib,
            "paper_id": str(props.get("paper_id", "") or ""),
            "paragraph_id": str(props.get("paragraph_id", "") or ""),
            "sentence_id": str(props.get("sentence_id", "") or ""),
            "text": str(props.get("text", "") or props.get("full_text", "") or ""),
            "title": str(props.get("title", "") or ""),
            "doi": str(props.get("doi", "") or ""),
        }
        if include_context:
            hit["context"] = self._expand_context(hit, props)
        return hit

    def _expand_context(self, hit: dict[str, Any], props: dict[str, Any]) -> dict[str, Any]:
        paper_id = str(hit.get("paper_id", "") or "")
        paragraph_id = str(hit.get("paragraph_id", "") or "")
        sentence_id = str(hit.get("sentence_id", "") or "")
        library_id = str(hit.get("library_id", "") or props.get("library_id", "") or "").strip()
        sentence = self._sentence_by_id.get(f"{library_id}::{sentence_id}", {})
        paragraph = self._paragraph_by_id.get(f"{library_id}::{paragraph_id}", {})
        document = self._document_by_id.get(f"{library_id}::{paper_id}", {})
        if not sentence and sentence_id:
            sentence = {
                "library_id": library_id,
                "sentence_id": sentence_id,
                "paragraph_id": paragraph_id,
                "paper_id": paper_id,
                "text": str(props.get("text", "") or ""),
                "source_html": str(props.get("source_html", "") or ""),
            }
        if not paragraph and paragraph_id:
            paragraph = {
                "library_id": library_id,
                "paragraph_id": paragraph_id,
                "paper_id": paper_id,
                "text": str(props.get("text", "") or ""),
                "source_html": str(props.get("source_html", "") or ""),
            }
        if not document and paper_id:
            document = {
                "library_id": library_id,
                "paper_id": paper_id,
                "doi": str(props.get("doi", "") or ""),
                "title": str(props.get("title", "") or ""),
                "full_text": str(props.get("full_text", "") or ""),
                "source_html": str(props.get("source_html", "") or ""),
            }
        return {"sentence": sentence, "paragraph": paragraph, "document": document}

    def answer(
        self,
        query: str,
        top_k: int = 5,
        levels: list[str] | None = None,
        library_id: str = "",
        keyword_weight: float = 0.4,
        rag_weight: float = 0.6,
    ) -> dict[str, Any]:
        retrieval = self.search(
            query=query,
            top_k=top_k,
            levels=levels or ["sentence"],
            library_id=library_id,
            keyword_weight=keyword_weight,
            rag_weight=rag_weight,
            include_expanded_context=True,
        )
        citations = retrieval["merged_hits"][:top_k]
        snippets = []
        for idx, hit in enumerate(citations, start=1):
            snippets.append(f"[{idx}] paper={hit.get('paper_id', '')} text={str(hit.get('text', '')).strip()[:400]}")
        prompt = (
            "你是文献问答助手。基于提供证据回答问题，并在答案中引用方括号编号。\n\n"
            f"问题：{query}\n\n"
            "证据：\n"
            + "\n".join(snippets)
        )
        answer = self.generator.complete(prompt, system_prompt="请严格基于证据回答。")
        return {"answer": answer, "citations": citations, "retrieval": retrieval}


def _level_to_class(level: str) -> str:
    lv = str(level or "sentence").strip().lower()
    if lv == "paragraph":
        return "LiteratureParagraph"
    if lv == "document":
        return "LiteratureDocument"
    return "LiteratureSentence"
