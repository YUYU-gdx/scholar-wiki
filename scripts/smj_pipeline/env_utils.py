from __future__ import annotations

import os
from pathlib import Path


def load_repo_env(env_file: str = ".env") -> Path | None:
    """Load KEY=VALUE pairs from repo-root .env into process environment.

    Existing process env vars are not overwritten.
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

