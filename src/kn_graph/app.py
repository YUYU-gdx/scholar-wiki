import logging
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from kn_graph.config import Settings, ensure_data_dirs
from kn_graph.migration import migrate_legacy_data
from kn_graph.services.graph_service import GraphService
from kn_graph.services.chat_service import ChatService
from kn_graph.services.literature_service import LiteratureService
from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services.workspace_service import WorkspaceService
from kn_graph.services.settings_service import SettingsService
from kn_graph.services.pipeline_stage_runtime import start_pipeline_stage_workers

from kn_graph.routers import graph, chat, literature, pipeline, workspace, settings as settings_router

logger = logging.getLogger(__name__)


def _get_frontend_dir() -> Path | None:
    """Locate the built frontend dist directory."""
    if getattr(sys, 'frozen', False):
        candidate = Path(sys._MEIPASS) / "frontend"
        if (candidate / "index.html").exists():
            return candidate
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "scholarai-workbench" / "dist"
    if (candidate / "index.html").exists():
        return candidate
    return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.load_global_settings()

    from kn_graph.services.pipeline_runtime import init_pipeline_settings
    init_pipeline_settings(settings)

    from kn_graph.services.library_registry import configure as configure_library_registry
    configure_library_registry(
        workspace_root=settings.workspaces_dir,
        registry_path=settings.registry_path,
        index_root=settings.indexes_dir,
    )

    ensure_data_dirs(settings)
    migrate_legacy_data(settings.data_dir)

    app = FastAPI(
        title="Scholar Wiki API",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    graph_service = GraphService(settings)
    chat_service = ChatService(settings)
    literature_service = LiteratureService(settings)
    pipeline_service = PipelineService(settings)
    workspace_service = WorkspaceService(settings)
    settings_service = SettingsService(settings, chat_service)

    # Startup-time minimal config sync for agent instances.
    # Hard fail on chat root, soft fail on per-library workspaces.
    from kn_graph.services.agent_workspace_guard import ensure_all_agent_workspaces_minimal_config
    guard_report = ensure_all_agent_workspaces_minimal_config(settings)
    for err in guard_report.get("errors", []) if isinstance(guard_report, dict) else []:
        text = str(err or "")
        if text.startswith("chat_root:"):
            raise RuntimeError(f"agent_workspace_guard_startup_failed:{text}")
        logger.warning("agent_workspace_guard_startup_warn:%s", text)

    app.include_router(graph.create_router(graph_service))
    app.include_router(graph.create_paper_router(graph_service))
    app.include_router(chat.create_router(chat_service))
    app.include_router(literature.create_router(literature_service, pipeline_service))
    app.include_router(pipeline.create_router(pipeline_service))
    app.include_router(workspace.create_router(workspace_service))
    app.include_router(settings_router.create_router(settings_service))

    if settings.pipeline_executor.strip().lower() == "stage_queue":
        workers = start_pipeline_stage_workers(settings)
        app.state.pipeline_stage_workers = workers
        logger.info("pipeline_stage_workers_started count=%s", len(workers))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    # Serve frontend static files (must be after all API routes so they take priority)
    frontend_dir = _get_frontend_dir()
    if frontend_dir:
        assets_dir = frontend_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend_assets")
        legacy_dir = frontend_dir / "frontend_legacy"
        if legacy_dir.is_dir():
            app.mount("/frontend_legacy", StaticFiles(directory=str(legacy_dir), html=True), name="frontend_legacy")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = frontend_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(frontend_dir / "index.html")
    else:
        logger.warning("Frontend dist not found; running API-only mode.")

    return app
