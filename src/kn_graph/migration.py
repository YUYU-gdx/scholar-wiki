from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            return False
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
    logger.info("migrated %s -> %s", src, dst)
    return True


def migrate_legacy_data(data_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    migrations: list[tuple[Path, Path]] = [
        (repo_root / "outputs" / "libraries" / "registry.json", data_dir / "libraries" / "registry.json"),
        (repo_root / "outputs" / "literature_libraries", data_dir / "libraries" / "indexes"),
        (repo_root / "outputs" / "workbench" / "workspace_layouts.json", data_dir / "workbench" / "layouts.json"),
        (repo_root / "outputs" / "workbench" / "pipeline_jobs.sqlite", data_dir / "pipeline" / "jobs.sqlite"),
        (repo_root / "jobs.db", data_dir / "pipeline" / "jobs.sqlite"),
    ]

    migrated_any = False
    for src, dst in migrations:
        if dst.exists():
            continue
        if _copy_if_exists(src, dst):
            migrated_any = True

    runs_src = repo_root / "outputs" / "runs"
    runs_dst = data_dir / "runs"
    if runs_src.is_dir() and not runs_dst.exists():
        shutil.copytree(str(runs_src), str(runs_dst))
        logger.info("migrated %s -> %s", runs_src, runs_dst)
        migrated_any = True
    elif runs_src.is_dir() and runs_dst.exists():
        active_src = runs_src / "active.json"
        active_dst = runs_dst / "active.json"
        if active_src.exists() and not active_dst.exists():
            shutil.copy2(str(active_src), str(active_dst))
            logger.info("migrated %s -> %s", active_src, active_dst)
            migrated_any = True

    if migrated_any:
        logger.info("legacy data migration completed into %s", data_dir)
    else:
        logger.debug("no legacy data to migrate")