import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    if os.name == "nt":
        return Path(r"D:\KNGraphApp")
    return Path.home() / ".kn_graph"


def load_repo_env(env_file: str = ".env") -> Path | None:
    """Load KEY=VALUE pairs from repo-root .env into process environment.

    Existing process env vars are not overwritten.
    Returns the resolved .env path, or None if not found.
    """
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / env_file
    if not path.exists():
        return None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return path


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8013

    data_dir: Path = Field(default_factory=_default_data_dir)

    chat_store_dsn: str = ""

    pipeline_job_store_dsn: str = ""
    pipeline_executor: str = "inline"
    pipeline_redis_url: str = "redis://127.0.0.1:6379/0"

    weaviate_url: str = "http://127.0.0.1:8090"

    llm_provider_config_path: str = "config/llm_providers.json"

    model_config = {"env_prefix": "KN_GRAPH_", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

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
