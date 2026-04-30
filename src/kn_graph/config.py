from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8013

    views_json: Optional[Path] = None
    allow_non_supply_chain: bool = False

    chat_store_dsn: str = ""

    pipeline_job_store_dsn: str = "sqlite:///jobs.db"
    pipeline_executor: str = "inline"
    pipeline_redis_url: str = "redis://127.0.0.1:6379/0"

    weaviate_url: str = "http://127.0.0.1:8090"

    llm_provider_config_path: str = "config/llm_providers.json"

    model_config = {"env_prefix": "KN_GRAPH_", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}