import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kn_graph.config import Settings, ensure_data_dirs
from kn_graph.migration import migrate_legacy_data
from kn_graph.services.graph_service import GraphService
from kn_graph.services.chat_service import ChatService
from kn_graph.services.literature_service import LiteratureService
from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services.workspace_service import WorkspaceService
from kn_graph.services.settings_service import SettingsService

from kn_graph.routers import graph, chat, literature, pipeline, workspace, settings as settings_router

logger = logging.getLogger(__name__)


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
    settings_service = SettingsService(settings, chat_service)

    # Ensure the chat Q&A skill is deployed to the root workspace at startup.
    # (Library workspaces get the extraction skill on first access.)
    from kn_graph.services.codex_library_config import bootstrap_workspace_project_skills
    bootstrap_workspace_project_skills(
        str(settings.workspaces_dir.resolve()),
        skill_names=["answer_library_question"],
    )

    app.include_router(graph.create_router(graph_service))
    app.include_router(graph.create_paper_router(graph_service))
    app.include_router(chat.create_router(chat_service))
    app.include_router(literature.create_router(literature_service))
    app.include_router(pipeline.create_router(pipeline_service))
    app.include_router(workspace.create_router(workspace_service))
    app.include_router(settings_router.create_router(settings_service))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app
