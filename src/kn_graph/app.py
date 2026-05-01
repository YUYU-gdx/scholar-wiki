import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kn_graph.config import Settings, ensure_data_dirs
from kn_graph.migration import migrate_legacy_data
from kn_graph.services.graph_service import GraphService
from kn_graph.services.chat_service import ChatService
from kn_graph.services.literature_service import LiteratureService
from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services.workspace_service import WorkspaceService

from kn_graph.routers import graph, chat, literature, pipeline, workspace
from kn_graph.routers.static_files import create_static_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    ensure_data_dirs(settings)
    migrate_legacy_data(settings.data_dir)

    app = FastAPI(
        title="KN Graph API",
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

    app.include_router(graph.create_router(graph_service))
    app.include_router(graph.create_paper_router(graph_service))
    app.include_router(chat.create_router(chat_service))
    app.include_router(literature.create_router(literature_service))
    app.include_router(pipeline.create_router(pipeline_service))
    app.include_router(workspace.create_router(workspace_service))

    frontend_dir = str(Path("frontend_legacy").resolve()) if Path("frontend_legacy").is_dir() else None
    workbench_dir = str((settings.data_dir / "workbench_spa").resolve()) if (settings.data_dir / "workbench_spa").is_dir() else None
    fallback_workbench = str((Path("frontend_legacy") / "workbench_spa").resolve()) if (Path("frontend_legacy") / "workbench_spa").is_dir() else None
    effective_workbench = workbench_dir or fallback_workbench
    static_router = create_static_router(frontend_dir, workbench_dir=effective_workbench)
    if static_router.routes:
        app.include_router(static_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app