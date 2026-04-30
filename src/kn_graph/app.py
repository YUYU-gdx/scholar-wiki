from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kn_graph.config import Settings
from kn_graph.services.graph_service import GraphService
from kn_graph.services.chat_service import ChatService
from kn_graph.services.literature_service import LiteratureService
from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services.workspace_service import WorkspaceService

from kn_graph.routers import graph, chat, literature, pipeline, workspace
from kn_graph.routers.static_files import create_static_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
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
    static_router = create_static_router(frontend_dir)
    if static_router.routes:
        app.include_router(static_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app