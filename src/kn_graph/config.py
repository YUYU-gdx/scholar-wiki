import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


def _default_data_dir() -> Path:
    env = os.getenv("KN_GRAPH_DATA_DIR", "").strip()
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(r"D:\KNGraphApp")
    return Path.home() / ".kn_graph"


class Settings(BaseModel):
    """Single source of truth for all non-agent application configuration.

    Populated at startup from {data_dir}/settings/global_settings.json.
    Only data_dir can be discovered from the KN_GRAPH_DATA_DIR env var
    (boot necessity); all other values must come from the JSON file.
    """

    # Boot (data_dir can be overridden via constructor arg from env/CLI)
    host: str = "127.0.0.1"
    port: int = 8013
    data_dir: Path = Field(default_factory=_default_data_dir)

    # Chat
    chat_store_dsn: str = ""
    chat_agent_backend: str = "codex"

    # Pipeline
    pipeline_job_store_dsn: str = ""
    pipeline_executor: str = "inline"
    pipeline_redis_url: str = "redis://127.0.0.1:6379/0"
    pipeline_fast_provider: str = "deepseek"
    pipeline_fast_model: str = ""
    pipeline_fast_endpoint_url: str = ""

    # Pipeline extraction mode: "fast" (direct LLM) or "agent" (agent-driven)
    pipeline_extraction_mode: str = "fast"

    # Pipeline agent (used when extraction_mode == "agent")
    pipeline_agent_backend: str = "codex"
    pipeline_agent_provider: str = "deepseek"
    pipeline_agent_model: str = ""
    pipeline_agent_api_key: str = ""
    pipeline_agent_base_url: str = ""
    pipeline_agent_endpoint_url: str = ""

    # API Keys
    mineru_api_key: str = ""
    zhipu_api_key: str = ""
    nvidia_api_key: str = ""
    deepseek_api_key: str = ""
    chromadb_path: str = ""
    mineru_api_base_url: str = "https://mineru.net/api/v4"

    # LLM Provider config
    llm_provider_config_path: str = "config/llm_providers.json"

    # Literature paths
    literature_library_index_root: str = "outputs/literature_libraries"
    literature_library_registry_path: str = ""
    literature_library_workspaces_root: str = ""
    literature_default_library_id: str = ""

    # Models
    graph_embedding_model: str = ""
    literature_embedding_model: str = "embedding-3"
    literature_chat_model: str = "glm-4.5-flash"

    # Limits
    literature_embed_max_chars: int = 8000
    literature_embed_batch_size: int = 32

    # Misc
    mineru_version: str = ""

    # ------------------------------------------------------------------
    # Load from persistent store
    # ------------------------------------------------------------------

    def load_global_settings(self) -> None:
        """Merge {data_dir}/settings/global_settings.json into this object."""
        store_path = self.data_dir / "settings" / "global_settings.json"
        if not store_path.exists():
            return
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
        except Exception:
            return

        # pipeline_agent (loaded before pipeline guard — independent category)
        pa = store.get("categories", {}).get("pipeline_agent", {})
        if isinstance(pa, dict):
            backend = str(pa.get("backend", "") or "").strip()
            if backend in ("codex", "claude_code", "gemini_cli"):
                self.pipeline_agent_backend = backend
            provider = str(pa.get("provider", "") or "").strip()
            if provider:
                self.pipeline_agent_provider = provider
            model = str(pa.get("model", "") or "").strip()
            if model:
                self.pipeline_agent_model = model
            api_key = str(pa.get("api_key", "") or "").strip()
            if api_key:
                self.pipeline_agent_api_key = api_key
            base_url = str(pa.get("base_url", "") or "").strip()
            if base_url:
                self.pipeline_agent_base_url = base_url
            endpoint_url = str(pa.get("endpoint_url", "") or "").strip()
            if endpoint_url:
                self.pipeline_agent_endpoint_url = endpoint_url

        pipeline = store.get("categories", {}).get("pipeline", {})
        if not isinstance(pipeline, dict):
            return

        # mineru_api_key
        val = str(pipeline.get("mineru_api_key", "") or "").strip()
        if val:
            self.mineru_api_key = val

        # pipeline extraction settings
        fast = str(pipeline.get("fast_provider", "") or "").strip()
        if fast:
            self.pipeline_fast_provider = fast
        model = str(pipeline.get("fast_model", "") or "").strip()
        if model:
            self.pipeline_fast_model = model
        endpoint = str(pipeline.get("fast_endpoint_url", "") or "").strip()
        if endpoint:
            self.pipeline_fast_endpoint_url = endpoint

        # fast_provider configs → provider-specific API keys
        fast_providers = pipeline.get("fast_providers", {})
        if isinstance(fast_providers, dict):
            for provider_id, field_name in [
                ("deepseek", "deepseek_api_key"),
                ("zhipu", "zhipu_api_key"),
                ("openai", ""),
                ("gemini", ""),
                ("anthropic", ""),
            ]:
                if not field_name:
                    continue
                provider_data = fast_providers.get(provider_id, {})
                if isinstance(provider_data, dict):
                    key = str(provider_data.get("api_key", "") or "").strip()
                    if key and not getattr(self, field_name, ""):
                        setattr(self, field_name, key)

        # extraction_mode
        mode = str(pipeline.get("extraction_mode", "") or "").strip().lower()
        if mode in ("fast", "agent"):
            self.pipeline_extraction_mode = mode

    # ------------------------------------------------------------------
    # Derived paths
    # ------------------------------------------------------------------

    @property
    def libraries_dir(self) -> Path:
        return self.data_dir / "libraries"

    @property
    def workspaces_dir(self) -> Path:
        return self.libraries_dir / "workspaces"

    @property
    def registry_path(self) -> Path:
        return self.libraries_dir / "registry.json"

    @property
    def indexes_dir(self) -> Path:
        return self.libraries_dir / "indexes"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def pipeline_db_path(self) -> Path:
        return self.data_dir / "pipeline" / "jobs.sqlite"

    @property
    def chat_store_path(self) -> Path:
        return self.data_dir / "chat" / "store.sqlite"

    @property
    def workspace_layouts_path(self) -> Path:
        return self.data_dir / "workbench" / "layouts.json"

    @property
    def codex_config_path(self) -> Path:
        return self.data_dir / "chat" / "codex_runner_config.json"

    @property
    def library_index_root_path(self) -> Path:
        path = self.literature_library_index_root.strip()
        return Path(path) if path else Path("outputs/literature_libraries")

    @property
    def library_registry_path(self) -> Path:
        path = self.literature_library_registry_path.strip()
        return Path(path) if path else self.libraries_dir / "registry.json"

    @property
    def library_workspaces_root_path(self) -> Path:
        path = self.literature_library_workspaces_root.strip()
        return Path(path) if path else self.workspaces_dir

    def resolve_graph_views_path(self, library_id: str = "") -> Path | None:
        lib = str(library_id or "").strip()
        if not lib:
            return None
        ws_path = self.workspaces_dir / lib / "graph_views.json"
        if ws_path.exists():
            return ws_path
        run_path = self.runs_dir / lib / "graph_views.json"
        if run_path.exists():
            return run_path
        return None


def ensure_data_dirs(settings: Settings) -> None:
    dirs = [
        settings.data_dir,
        settings.libraries_dir,
        settings.workspaces_dir,
        settings.indexes_dir,
        settings.data_dir / "pipeline",
        settings.data_dir / "chat",
        settings.data_dir / "workbench",
        settings.runs_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
