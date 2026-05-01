from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse, Response


_THREE_FRONTENDS = [
    ("", "graph_3d"),
    ("chat", "chat_embed"),
    ("workbench", "workbench_spa"),
]

_CHAT_ENTRY_SNIPPET = (
    "<a id=\"kn-chat-entry\" href=\"/frontend/chat/\" "
    "style=\"position:fixed;right:20px;bottom:20px;z-index:9999;"
    "background:#0f766e;color:#fff;text-decoration:none;padding:10px 14px;"
    "border-radius:999px;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.2);\">AI \u95ee\u7b54</a>"
)


def _inject_chat_entry(html: str) -> str:
    if "id=\"kn-chat-entry\"" in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", _CHAT_ENTRY_SNIPPET + "</body>")
    return html + _CHAT_ENTRY_SNIPPET


def create_static_router(frontend_dir: str | None = None, workbench_dir: str | None = None) -> APIRouter:
    router = APIRouter()

    root = Path(frontend_dir).resolve() if frontend_dir else Path("frontend_legacy").resolve()

    frontend_mounts: dict[str, Path] = {}
    for prefix, subdir in _THREE_FRONTENDS:
        if prefix == "workbench" and workbench_dir:
            candidate = Path(workbench_dir).resolve()
        else:
            candidate = root / subdir
        if candidate.is_dir():
            frontend_mounts[prefix] = candidate

    if not frontend_mounts:
        return router

    def _resolve_path(prefix: str, rel_path: str) -> Path | None:
        mount_dir = frontend_mounts[prefix]
        safe = rel_path.lstrip("/")
        if not safe:
            safe = "index.html"
        path = (mount_dir / safe).resolve()
        if not str(path).startswith(str(mount_dir.resolve())):
            return None
        if not path.exists() or not path.is_file():
            return None
        return path

    if "" in frontend_mounts:

        @router.get("/frontend/{path:path}", response_model=None)
        async def serve_graph_frontend(path: str) -> Response:
            resolved = _resolve_path("", path)
            if resolved is None:
                resolved = _resolve_path("", "index.html")
                if resolved is None:
                    return HTMLResponse("<h1>404</h1>", status_code=404)
            if resolved.name.lower() == "index.html":
                try:
                    text = resolved.read_text(encoding="utf-8", errors="ignore")
                    text = _inject_chat_entry(text)
                    return HTMLResponse(text)
                except Exception:
                    pass
            return FileResponse(resolved)

        @router.get("/frontend", response_model=None)
        @router.get("/frontend/", response_model=None)
        async def serve_graph_index() -> Response:
            resolved = _resolve_path("", "index.html")
            if resolved is None:
                return HTMLResponse("<h1>404</h1>", status_code=404)
            try:
                text = resolved.read_text(encoding="utf-8", errors="ignore")
                text = _inject_chat_entry(text)
                return HTMLResponse(text)
            except Exception:
                return FileResponse(resolved)

    if "chat" in frontend_mounts:

        @router.get("/frontend/chat", response_model=None)
        @router.get("/frontend/chat/", response_model=None)
        async def serve_chat_index() -> Response:
            resolved = _resolve_path("chat", "index.html")
            if resolved is None:
                return HTMLResponse("<h1>404</h1>", status_code=404)
            return FileResponse(resolved)

        @router.get("/frontend/chat/{path:path}", response_model=None)
        async def serve_chat_static(path: str) -> Response:
            resolved = _resolve_path("chat", path)
            if resolved is None:
                return HTMLResponse("<h1>404</h1>", status_code=404)
            return FileResponse(resolved)

    if "workbench" in frontend_mounts:

        @router.get("/frontend/workbench", response_model=None)
        @router.get("/frontend/workbench/", response_model=None)
        async def serve_workbench_index() -> Response:
            resolved = _resolve_path("workbench", "index.html")
            if resolved is None:
                return HTMLResponse("<h1>404</h1>", status_code=404)
            return FileResponse(resolved)

        @router.get("/frontend/workbench/{path:path}", response_model=None)
        async def serve_workbench_static(path: str) -> Response:
            resolved = _resolve_path("workbench", path)
            if resolved is None:
                resolved = _resolve_path("workbench", "index.html")
                if resolved is None:
                    return HTMLResponse("<h1>404</h1>", status_code=404)
            return FileResponse(resolved)

    return router