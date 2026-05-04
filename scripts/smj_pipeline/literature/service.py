from __future__ import annotations

from dataclasses import dataclass
import html
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import uuid
from typing import Any

import requests


def _load_zhipu_client_class():
    module_path = Path(__file__).resolve().parent.parent / "llm" / "zhipu_client.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_llm_zhipu_client_for_literature", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ZhipuChatCompletionsClient


def _load_library_registry_module():
    module_path = Path(__file__).resolve().parent.parent / "library_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_library_registry_for_literature", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_runtime_conventions_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime_conventions.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_runtime_conventions_for_literature", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RUNTIME_CONVENTIONS = _load_runtime_conventions_module()

# Ensure the parent scripts directory is on sys.path so that module-level
# imports inside mineru_single_pdf_runner.py (e.g. "from mineru_agent_common
# import safe_id") resolve correctly.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_MINERU_SINGLE_MOD = None


def _get_mineru_single_mod():
    """Lazy-load the mineru_single_pdf_runner module (cloud API)."""
    global _MINERU_SINGLE_MOD
    if _MINERU_SINGLE_MOD is None:
        module_path = Path(__file__).resolve().parent.parent / "mineru_single_pdf_runner.py"
        spec = importlib.util.spec_from_file_location("smj_pipeline_mineru_single_for_literature", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load module: {module_path}")
        _MINERU_SINGLE_MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MINERU_SINGLE_MOD)
    return _MINERU_SINGLE_MOD


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
class ZhipuEmbeddingClient:
    api_key: str
    model: str = "embedding-3"
    base_url: str = "https://open.bigmodel.cn/api/paas/v4/embeddings"
    timeout_seconds: int = 120
    max_retries: int = 3

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        max_chars = int(os.getenv("LITERATURE_EMBED_MAX_CHARS", "8000") or 8000)
        batch_size = max(1, int(os.getenv("LITERATURE_EMBED_BATCH_SIZE", "32") or 32))
        prepared = [str(t or "")[:max_chars] for t in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(prepared), batch_size):
            batch = prepared[i : i + batch_size]
            vectors.extend(self._embed_batch(batch))
        if len(vectors) != len(prepared):
            raise ValueError("zhipu embedding response length mismatch")
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
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
                    raise ValueError("zhipu embedding response length mismatch")
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


class _NoopEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class _NoopGeneratorClient:
    def complete(self, prompt: str, system_prompt: str = "") -> str:
        _ = prompt, system_prompt
        return "当前未配置文本生成模型，仅返回检索结果。"


class WeaviateRestClient:
    def __init__(self, base_url: str, api_key: str = "", timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self._library_id_supported: bool | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.request(
            method=method,
            url=f"{self.base_url}{path}",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout_seconds,
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:1200]
            raise RuntimeError(f"weaviate_http_error:{resp.status_code}:{method}:{path}:{detail}")
        if not resp.text.strip():
            return {}
        return resp.json()

    def ensure_literature_schema(self) -> None:
        existing = self._request("GET", "/v1/schema")
        classes = {
            str(cls.get("class", "")): cls
            for cls in (existing.get("classes", []) if isinstance(existing, dict) else [])
            if isinstance(cls, dict)
        }
        for class_def in self._default_schema():
            if class_def["class"] in classes:
                try:
                    self._ensure_class_properties(class_def)
                except Exception:
                    # Keep backward compatibility when schema is temporarily read-only.
                    pass
            else:
                self._request("POST", "/v1/schema", class_def)
        self._library_id_supported = self.supports_library_id(refresh=True)

    def supports_library_id(self, refresh: bool = False) -> bool:
        if self._library_id_supported is not None and not refresh:
            return self._library_id_supported
        try:
            schema = self._request("GET", "/v1/schema")
        except Exception:
            self._library_id_supported = False
            return False
        classes = {
            str(cls.get("class", "")): cls
            for cls in (schema.get("classes", []) if isinstance(schema, dict) else [])
            if isinstance(cls, dict)
        }
        ok = True
        for class_name in ("LiteratureSentence", "LiteratureParagraph", "LiteratureDocument"):
            cls = classes.get(class_name, {})
            props = {
                str(p.get("name", "")).strip()
                for p in (cls.get("properties", []) if isinstance(cls, dict) else [])
                if isinstance(p, dict)
            }
            if "library_id" not in props:
                ok = False
                break
        self._library_id_supported = ok
        return ok

    def _ensure_class_properties(self, class_def: dict[str, Any]) -> None:
        class_name = str(class_def.get("class", "")).strip()
        if not class_name:
            return
        existing = self._request("GET", f"/v1/schema/{class_name}")
        existing_props = {
            str(p.get("name", "")).strip()
            for p in (existing.get("properties", []) if isinstance(existing, dict) else [])
            if isinstance(p, dict)
        }
        for prop in class_def.get("properties", []):
            if not isinstance(prop, dict):
                continue
            name = str(prop.get("name", "")).strip()
            if not name or name in existing_props:
                continue
            self._request("POST", f"/v1/schema/{class_name}/properties", prop)

    def upsert(self, class_name: str, object_id: str, properties: dict[str, Any], vector: list[float]) -> None:
        payload_props = dict(properties)
        if "library_id" in payload_props and not self.supports_library_id():
            payload_props.pop("library_id", None)
        body = {
            "class": class_name,
            "id": object_id,
            "properties": payload_props,
            "vector": vector,
        }
        try:
            self._request("POST", "/v1/objects", body)
            return
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "weaviate_http_error:422" not in text and "already exists" not in text.lower():
                raise
        self._request("PUT", f"/v1/objects/{object_id}", body)

    def bm25_search(self, class_name: str, query: str, limit: int, library_id: str = "") -> list[dict[str, Any]]:
        return self._graphql_search(class_name=class_name, query=query, limit=limit, use_vector=False, vector=None, library_id=library_id)

    def vector_search(self, class_name: str, vector: list[float], limit: int, library_id: str = "") -> list[dict[str, Any]]:
        return self._graphql_search(class_name=class_name, query="", limit=limit, use_vector=True, vector=vector, library_id=library_id)

    def _graphql_search(
        self,
        class_name: str,
        query: str,
        limit: int,
        use_vector: bool,
        vector: list[float] | None,
        library_id: str = "",
    ) -> list[dict[str, Any]]:
        include_library = self.supports_library_id()
        props = self._class_props(class_name, include_library=include_library)
        props_text = " ".join(props)
        parts: list[str] = []
        if use_vector:
            vector_body = ", ".join(f"{float(v):.10f}" for v in (vector or []))
            parts.append(f"nearVector:{{vector:[{vector_body}]}}")
        else:
            q = query.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'bm25:{{query:"{q}"}}')
        lib = str(library_id or "").strip()
        if lib and include_library:
            lib_safe = lib.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'where:{{path:["library_id"],operator:Equal,valueText:"{lib_safe}"}}')
        parts.append(f"limit:{int(limit)}")
        clause = "(" + ", ".join(parts) + ")"
        gql = f"{{Get{{{class_name}{clause}{{{props_text} _additional{{id score distance}}}}}}}}"
        resp = self._request("POST", "/v1/graphql", {"query": gql})
        rows = (((resp.get("data", {}) or {}).get("Get", {}) or {}).get(class_name, []) if isinstance(resp, dict) else [])
        if not isinstance(rows, list):
            rows = []
        out: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            additional = item.get("_additional", {}) if isinstance(item.get("_additional"), dict) else {}
            item_id = str(additional.get("id", "") or item.get("sentence_id", "") or item.get("paragraph_id", "") or item.get("paper_id", ""))
            distance = additional.get("distance")
            score = additional.get("score")
            if score is None and isinstance(distance, (int, float)):
                score = 1.0 / (1.0 + float(distance))
            out.append(
                {
                    "id": item_id,
                    "score": float(score or 0.0),
                    "properties": {k: v for k, v in item.items() if k != "_additional"},
                }
            )
        return out

    @staticmethod
    def _class_props(class_name: str, include_library: bool = True) -> list[str]:
        base = ["paper_id", "doi", "title"]
        if include_library:
            base = ["library_id", *base]
        if class_name == "LiteratureDocument":
            return [*base, "full_text", "source_html", "metadata_json"]
        if class_name == "LiteratureParagraph":
            return [*base, "paragraph_id", "text", "sentence_ids", "source_html"]
        return [*base, "paragraph_id", "sentence_id", "text", "position", "source_html"]

    @staticmethod
    def _default_schema() -> list[dict[str, Any]]:
        return [
            {
                "class": "LiteratureSentence",
                "vectorizer": "none",
                "properties": [
                    {"name": "library_id", "dataType": ["text"]},
                    {"name": "paper_id", "dataType": ["text"]},
                    {"name": "doi", "dataType": ["text"]},
                    {"name": "title", "dataType": ["text"]},
                    {"name": "paragraph_id", "dataType": ["text"]},
                    {"name": "sentence_id", "dataType": ["text"]},
                    {"name": "text", "dataType": ["text"]},
                    {"name": "position", "dataType": ["int"]},
                    {"name": "source_html", "dataType": ["text"]},
                ],
            },
            {
                "class": "LiteratureParagraph",
                "vectorizer": "none",
                "properties": [
                    {"name": "library_id", "dataType": ["text"]},
                    {"name": "paper_id", "dataType": ["text"]},
                    {"name": "doi", "dataType": ["text"]},
                    {"name": "title", "dataType": ["text"]},
                    {"name": "paragraph_id", "dataType": ["text"]},
                    {"name": "text", "dataType": ["text"]},
                    {"name": "sentence_ids", "dataType": ["text[]"]},
                    {"name": "source_html", "dataType": ["text"]},
                ],
            },
            {
                "class": "LiteratureDocument",
                "vectorizer": "none",
                "properties": [
                    {"name": "library_id", "dataType": ["text"]},
                    {"name": "paper_id", "dataType": ["text"]},
                    {"name": "doi", "dataType": ["text"]},
                    {"name": "title", "dataType": ["text"]},
                    {"name": "full_text", "dataType": ["text"]},
                    {"name": "source_html", "dataType": ["text"]},
                    {"name": "metadata_json", "dataType": ["text"]},
                ],
            },
        ]


class LiteratureService:
    def __init__(
        self,
        weaviate_client: Any | None = None,
        embedding_client: Any | None = None,
        generator_client: Any | None = None,
    ) -> None:
        self.weaviate = weaviate_client or self._build_default_weaviate()
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

    def _normalize_storage_path(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.replace("\\", "/")

    def _default_library_id(self) -> str:
        return (os.getenv("LITERATURE_DEFAULT_LIBRARY_ID", "") or "").strip()

    def _library_index_root(self) -> Path:
        root = os.getenv("LITERATURE_LIBRARY_INDEX_ROOT", "outputs/literature_libraries").strip() or "outputs/literature_libraries"
        return Path(root)

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
        try:
            lr_mod = _load_library_registry_module()
            registry = lr_mod.ensure_registry()
            root = str(lr_mod.resolve_workspace_root(registry, lib) or "").strip()
        except Exception:
            root = ""
        if not root:
            return None
        path = Path(root).resolve()
        path.mkdir(parents=True, exist_ok=True)
        self._workspace_root_cache[lib] = path
        return path

    def _paper_key_for_row(self, row: dict[str, Any], source_path: Path | None, html_text: str) -> str:
        doi_norm = _normalize_doi_for_key(str(row.get("doi", "") or ""))
        # If the DOI is a synthetic job ID, prefer the title
        if doi_norm and not doi_norm.startswith("job_"):
            return f"doi_{doi_norm}"
        title = str(row.get("title", "") or "").strip()
        if title:
            title_key = _safe_segment(title)
            if title_key and title_key not in {"job", "item", "paper", "article"}:
                return f"title_{title_key[:80]}"
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

    def _run_mineru_cloud_to_dir(self, source_pdf: Path, out_dir: Path) -> dict[str, Any]:
        """Run Mineru cloud API to parse a single PDF, placing outputs in *out_dir*."""
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        mod = _get_mineru_single_mod()

        # parse_single_pdf creates parse/ inside the run_dir, so we use an
        # intermediate work directory and then copy results into out_dir.
        work_dir = out_dir.parent / "_mineru_cloud_work"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

        try:
            result = mod.parse_single_pdf(source_pdf, work_dir, options={})
        except Exception as exc:
            raise RuntimeError(f"mineru_cloud_failed: {exc}") from exc

        markdown_path = Path(str(result.get("markdown_path", "") or ""))
        if not markdown_path.exists():
            raise RuntimeError("mineru_cloud_produced_no_markdown")

        md_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
        md_title = _extract_first_md_h1(md_text)

        # Name the canonical markdown file by the first H1 heading (same
        # behaviour the old local-mineru path had via _safe_windows_filename).
        md_name = _safe_windows_filename(md_title, fallback=markdown_path.stem) + ".md"
        target_md = out_dir / md_name
        shutil.copy2(str(markdown_path), str(target_md))

        html_text = f"<html><body><pre>{html.escape(md_text)}</pre></body></html>"
        target_html = out_dir / f"{_safe_windows_filename(md_title, fallback='parsed')}.html"
        target_html.write_text(html_text, encoding="utf-8")

        # Copy unpacked zip contents (images, supplementary files) into out_dir
        # Copy unpacked zip contents (images, supplementary files) into out_dir.
        zip_unpacked = work_dir / "parse" / "mineru_zip_unpacked"
        if zip_unpacked.exists():
            for item in zip_unpacked.iterdir():
                dest = out_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    shutil.copytree(str(item), str(dest))
                else:
                    shutil.copy2(str(item), str(dest))

        # Clean up intermediate work directory.
        shutil.rmtree(work_dir, ignore_errors=True)

        html_files = list(out_dir.rglob("*.html"))
        md_files = list(out_dir.rglob("*.md"))

        return {
            "html_text": html_text,
            "source_kind": "html",
            "html_files": [str(x.resolve()) for x in html_files],
            "md_files": [str(x.resolve()) for x in md_files],
            "main_md_path": str(target_md.resolve()),
            "md_title": md_title,
            "command": ["mineru_cloud_api"],
        }

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
            parser_version = str(os.getenv("MINERU_VERSION", "") or "").strip() or "unknown"
            parser_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            mineru = self._run_mineru_cloud_to_dir(source_pdf, mineru_latest_dir)
            html_text = str(mineru.get("html_text", "") or "")
            mineru_main_md_path = str(mineru.get("main_md_path", "") or "")
            # MD library path points into the same paper directory (derived/mineru/latest)
            md_library_path = str(mineru_latest_dir.resolve())
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

    @staticmethod
    def _filter_rows_by_paper_ids(rows: list[dict[str, Any]], allowed_paper_ids: set[str]) -> list[dict[str, Any]]:
        if not allowed_paper_ids:
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            props = row.get("properties", {}) if isinstance(row.get("properties"), dict) else {}
            pid = str(props.get("paper_id", "") or "").strip()
            if pid and pid in allowed_paper_ids:
                out.append(row)
        return out

    def _build_default_weaviate(self) -> WeaviateRestClient:
        base_url = ""
        candidates = _RUNTIME_CONVENTIONS.build_weaviate_base_url_candidates()
        for candidate in candidates:
            try:
                resp = requests.get(candidate.rstrip("/") + "/v1/.well-known/ready", timeout=1.2)
                if resp.status_code < 500:
                    base_url = candidate
                    break
            except Exception:
                continue
        if not base_url:
            base_url = candidates[0]
        api_key = os.getenv("WEAVIATE_API_KEY", "").strip()
        return WeaviateRestClient(base_url=base_url, api_key=api_key)

    def _build_default_embedding(self) -> ZhipuEmbeddingClient:
        api_key = os.getenv("ZHIPU_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("missing env: ZHIPU_API_KEY")
        model = os.getenv("LITERATURE_EMBEDDING_MODEL", "embedding-3").strip() or "embedding-3"
        return ZhipuEmbeddingClient(api_key=api_key, model=model)

    def _build_default_generator(self) -> Any:
        api_key = os.getenv("ZHIPU_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("missing env: ZHIPU_API_KEY")
        model = os.getenv("LITERATURE_CHAT_MODEL", "glm-4.5-flash").strip() or "glm-4.5-flash"
        zhipu_cls = _load_zhipu_client_class()
        return zhipu_cls(api_key=api_key, model=model)

    def import_manifest(self, manifest_path: Path | str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options if isinstance(options, dict) else {}
        library_id = str(options.get("library_id", "") or self._default_library_id()).strip()
        path = Path(manifest_path)
        rows = _iter_jsonl(path)
        self.weaviate.ensure_literature_schema()
        imported = 0
        sent_count = 0
        para_count = 0
        doc_count = 0
        imported_paper_ids: list[str] = []
        materialized_rows: list[dict[str, Any]] = []
        workspace_path = ""
        for row in rows:
            result = self._import_row(row, library_id=library_id)
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
        return {
            "manifest_path": str(path),
            "library_id": library_id,
            "imported_count": imported,
            "sentence_count": sent_count,
            "paragraph_count": para_count,
            "document_count": doc_count,
            "workspace_path": workspace_path,
            "materialized_papers": materialized_rows,
        }

    def _import_row(self, row: dict[str, Any], library_id: str = "") -> dict[str, Any]:
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
        paragraph_vectors = self.embedding.embed_texts([str(p.get("text", "")) for p in paragraphs])
        document_vectors = self.embedding.embed_texts([str(paper.get("full_text", ""))])

        for sentence, vector in zip(sentences, sentence_vectors):
            sid = str(sentence["sentence_id"])
            sentence["library_id"] = library_id
            sentence["source_html"] = paper["source_html"]
            self._sentence_by_id[f"{library_id}::{sid}"] = dict(sentence)
            object_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"LiteratureSentence:{library_id}:{paper_id}:{sid}"))
            self.weaviate.upsert("LiteratureSentence", object_id, sentence, vector)

        for paragraph, vector in zip(paragraphs, paragraph_vectors):
            pid = str(paragraph["paragraph_id"])
            paragraph["library_id"] = library_id
            paragraph["source_html"] = paper["source_html"]
            self._paragraph_by_id[f"{library_id}::{pid}"] = dict(paragraph)
            object_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"LiteratureParagraph:{library_id}:{paper_id}:{pid}"))
            self.weaviate.upsert("LiteratureParagraph", object_id, paragraph, vector)

        self._document_by_id[f"{library_id}::{paper_id}"] = dict(paper)
        object_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"LiteratureDocument:{library_id}:{paper_id}"))
        self.weaviate.upsert(
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
            "document_count": 1,
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
        mod = _get_mineru_single_mod()
        with tempfile.TemporaryDirectory(prefix="mineru_cloud_normalize_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            result = mod.parse_single_pdf(source_pdf, tmp_path, options={})
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
        supports_native_filter = self.weaviate.supports_library_id()
        allowed_paper_ids = self._load_library_paper_ids(lib) if lib and not supports_native_filter else set()
        filter_mode = "none"
        if lib:
            filter_mode = "weaviate_where" if supports_native_filter else "paper_id_registry"
        filter_applied = bool(not lib or (supports_native_filter or bool(allowed_paper_ids)))
        fetch_limit = top_k if (not lib or supports_native_filter) else min(max(top_k * 8, 50), 500)
        for level in levels:
            class_name = _level_to_class(level)
            try:
                kw_rows = self.weaviate.bm25_search(
                    class_name,
                    query=query,
                    limit=fetch_limit,
                    library_id=lib if supports_native_filter else "",
                )
            except Exception as exc:  # noqa: BLE001
                kw_rows = []
                degraded_routes.append(f"{level}:keyword:{exc}")
            vg_rows: list[dict[str, Any]] = []
            if isinstance(query_vec, list) and len(query_vec) > 0:
                try:
                    vg_rows = self.weaviate.vector_search(
                        class_name,
                        vector=query_vec,
                        limit=fetch_limit,
                        library_id=lib if supports_native_filter else "",
                    )
                except Exception as exc:  # noqa: BLE001
                    vg_rows = []
                    degraded_routes.append(f"{level}:vector:{exc}")
            if lib and not supports_native_filter:
                kw_rows = self._filter_rows_by_paper_ids(kw_rows, allowed_paper_ids)
                vg_rows = self._filter_rows_by_paper_ids(vg_rows, allowed_paper_ids)
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
                "library_filter_applied": filter_applied,
                "library_filter_mode": filter_mode,
                "library_registry_paper_count": len(allowed_paper_ids),
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
