from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_local_modules():
    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from scripts.smj_pipeline import agent_runner as ar  # noqa: WPS433
    from scripts.smj_pipeline import codex_library_config as clc  # noqa: WPS433
    from scripts.smj_pipeline import library_registry as lr  # noqa: WPS433

    return ar, clc, lr


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test: call Codex App Server using project chat logic.")
    parser.add_argument("--library-id", default="", help="Target literature library id. Empty means registry default.")
    parser.add_argument("--question", default="供应链韧性如何影响企业绩效？", help="Question to ask codex.")
    parser.add_argument("--codex-config", default="outputs/chat/codex_runner_config.json", help="Codex runner config path.")
    args = parser.parse_args()

    ar, clc, lr = _load_local_modules()
    registry = lr.ensure_registry()
    library_id = str(args.library_id or registry.get("default_library_id", "") or "").strip()
    if not library_id:
        raise RuntimeError("library_id_missing")
    workspace = str(lr.resolve_workspace_root(registry, library_id) or "").strip()
    if not workspace:
        raise RuntimeError(f"codex_workspace_path_missing:library_id={library_id}")
    workdir = Path(workspace).resolve()
    if (not workdir.exists()) or (not workdir.is_dir()):
        raise RuntimeError(f"codex_workspace_path_invalid:library_id={library_id}:path={workdir}")

    cfg_path = (_repo_root() / str(args.codex_config)).resolve()
    factory = ar.AgentRunnerFactory(cfg_path)
    runner = factory.build("codex")
    health = runner.health()
    print("[health]", json.dumps(health, ensure_ascii=False))
    if not bool(health.get("available")):
        raise RuntimeError(f"codex_unavailable:{health}")

    library_cfg = clc.load_or_init_library_codex_config(str(workdir), library_id=library_id)
    runtime_overrides: dict[str, Any] = {
        "codex_home": str(library_cfg.get("codex_home", "") or "").strip(),
        "mcp_servers": library_cfg.get("mcp_servers", []),
        "mcp_whitelist": library_cfg.get("mcp_whitelist", []),
        "skills_whitelist": library_cfg.get("skills_whitelist", []),
        "skill_name": str(library_cfg.get("skill_name", "") or "").strip(),
        "skill_path": str(library_cfg.get("skill_path", "") or "").strip(),
    }

    print(f"[run] library_id={library_id} workdir={workdir}")
    print("[run] sending direct user query to Codex App Server")
    result = runner.run_turn(
        query=str(args.question or ""),
        workdir=str(workdir),
        library_id=library_id,
        runtime_overrides=runtime_overrides,
    )
    print("[answer]")
    print(str(result.get("answer", "") or ""))
    print("[meta]", json.dumps({"thread_id": result.get("thread_id"), "turn_id": result.get("turn_id")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
