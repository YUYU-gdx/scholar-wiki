from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def _load_module(relative_path: str, module_name: str):
    module_path = Path(__file__).resolve().parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_ENV_MOD = _load_module("env_utils.py", "smj_pipeline_env_utils_for_literature")
_LITERATURE_MOD = _load_module("literature/service.py", "smj_pipeline_literature_service_for_runner")
load_repo_env = _ENV_MOD.load_repo_env
LiteratureService = _LITERATURE_MOD.LiteratureService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run literature import/index pipeline.")
    parser.add_argument("--manifest-path", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    load_repo_env()
    args = parse_args()
    service = LiteratureService()
    result = service.import_manifest(args.manifest_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
