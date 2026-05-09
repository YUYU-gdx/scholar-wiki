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
    """Application configuration.

    Static fields (boot / derived paths) are Pydantic model fields.
    Dynamic fields (user-configurable via the UI) are @property getters
    that read from {data_dir}/settings/global_settings.json on every access,
    so changes take effect immediately without a restart.
    """

    # ------------------------------------------------------------------
    # Boot config (not persisted to global_settings.json)
    # ------------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8013
    data_dir: Path = Field(default_factory=_default_data_dir)

    # ------------------------------------------------------------------
    # Static config — defaults only, not user-modifiable via UI
    # ------------------------------------------------------------------
    chat_store_dsn: str = ""
    chat_agent_backend: str = "codex"

    pipeline_job_store_dsn: str = ""
    pipeline_executor: str = "inline"
    pipeline_redis_url: str = "redis://127.0.0.1:6379/0"

    llm_provider_config_path: str = "config/llm_providers.json"

    literature_default_library_id: str = ""

    graph_embedding_model: str = ""
    literature_embedding_model: str = "embedding-3"
    literature_chat_model: str = "glm-4.5-flash"

    literature_embed_max_chars: int = 8000
    literature_embed_batch_size: int = 32

    mineru_version: str = ""
    mineru_api_base_url: str = "https://mineru.net/api/v4"

    # ------------------------------------------------------------------
    # Dynamic config — reads from global_settings.json on every access
    # ------------------------------------------------------------------

    @property
    def _store(self) -> dict:
        """Read global_settings.json from disk (no caching)."""
        path = self.data_dir / "settings" / "global_settings.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _cat(self, name: str) -> dict:
        cat = self._store.get("categories", {}).get(name, {})
        return cat if isinstance(cat, dict) else {}

    # -- pipeline category --

    @property
    def mineru_api_key(self) -> str:
        return str(self._cat("pipeline").get("mineru_api_key", "") or "").strip()

    @property
    def pipeline_fast_provider(self) -> str:
        return str(self._cat("pipeline").get("fast_provider", "") or "deepseek").strip()

    @property
    def pipeline_fast_model(self) -> str:
        active = self.pipeline_fast_provider
        providers = self._cat("pipeline").get("fast_providers", {})
        if isinstance(providers, dict):
            p = providers.get(active, {})
            if isinstance(p, dict):
                return str(p.get("model", "") or "").strip()
        return ""

    @property
    def pipeline_fast_endpoint_url(self) -> str:
        active = self.pipeline_fast_provider
        providers = self._cat("pipeline").get("fast_providers", {})
        if isinstance(providers, dict):
            p = providers.get(active, {})
            if isinstance(p, dict):
                return str(p.get("endpoint_url", "") or "").strip()
        return ""

    @property
    def pipeline_extraction_mode(self) -> str:
        mode = str(self._cat("pipeline").get("extraction_mode", "") or "fast").strip().lower()
        return mode if mode in ("fast", "agent") else "fast"

    def _provider_api_key(self, provider_id: str) -> str:
        providers = self._cat("pipeline").get("fast_providers", {})
        if isinstance(providers, dict):
            p = providers.get(provider_id, {})
            if isinstance(p, dict):
                return str(p.get("api_key", "") or "").strip()
        return ""

    @property
    def deepseek_api_key(self) -> str:
        return self._provider_api_key("deepseek")

    @property
    def zhipu_api_key(self) -> str:
        return self._provider_api_key("zhipu")

    # -- embedding category --

    @property
    def embedding_provider(self) -> str:
        return str(self._cat("embedding").get("provider", "") or "zhipu").strip()

    def _embedding_provider_data(self) -> dict:
        active = self.embedding_provider
        providers = self._cat("embedding").get("providers", {})
        if isinstance(providers, dict):
            p = providers.get(active, {})
            if isinstance(p, dict):
                return p
        return {}

    @property
    def embedding_model(self) -> str:
        return str(self._embedding_provider_data().get("model", "") or "").strip()

    @property
    def embedding_api_key(self) -> str:
        return str(self._embedding_provider_data().get("api_key", "") or "").strip()

    @property
    def embedding_base_url(self) -> str:
        return str(self._embedding_provider_data().get("base_url", "") or "").strip()

    @property
    def embedding_endpoint_url(self) -> str:
        return str(self._embedding_provider_data().get("endpoint_url", "") or "").strip()

    # -- pipeline_agent category --

    @property
    def pipeline_agent_backend(self) -> str:
        backend = str(self._cat("pipeline_agent").get("backend", "") or "codex").strip().lower()
        return backend if backend in ("codex", "claude_code", "gemini_cli") else "codex"

    @property
    def pipeline_agent_provider(self) -> str:
        return str(self._cat("pipeline_agent").get("provider", "") or "deepseek").strip()

    @property
    def pipeline_agent_model(self) -> str:
        return str(self._cat("pipeline_agent").get("model", "") or "").strip()

    @property
    def pipeline_agent_api_key(self) -> str:
        return str(self._cat("pipeline_agent").get("api_key", "") or "").strip()

    @property
    def pipeline_agent_base_url(self) -> str:
        return str(self._cat("pipeline_agent").get("base_url", "") or "").strip()

    @property
    def pipeline_agent_endpoint_url(self) -> str:
        return str(self._cat("pipeline_agent").get("endpoint_url", "") or "").strip()

    @property
    def pipeline_agent_reasoning_effort(self) -> str:
        raw = str(self._cat("pipeline_agent").get("reasoning_effort", "") or "").strip().lower()
        return raw

    # ------------------------------------------------------------------
    # load_global_settings — kept as no-op for backward compatibility
    # ------------------------------------------------------------------

    def load_global_settings(self) -> None:
        """No-op: dynamic fields read from disk on every access.

        Kept for backward compatibility with existing callers
        (app.py, __main__.py, celery_app.py, etc.).
        """
        return

    # ------------------------------------------------------------------
    # Derived paths (computed from data_dir, not stored)
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
