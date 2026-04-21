from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    root = Path(__file__).resolve().parent
    env_mod = _load_module(root / "env_utils.py", "smj_pipeline_env_utils_for_dataset_tools")
    env_mod.load_repo_env()
    tools_mod = _load_module(root / "literature" / "dataset_tools.py", "smj_pipeline_literature_dataset_tools_runner")
    tools_mod.main()


if __name__ == "__main__":
    main()
