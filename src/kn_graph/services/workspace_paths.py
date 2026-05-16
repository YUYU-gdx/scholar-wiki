from __future__ import annotations

from pathlib import Path


def validate_library_id(library_id: str) -> str:
    lib = str(library_id or "").strip()
    if not lib:
        raise ValueError("library_id_required")
    if Path(lib).is_absolute() or lib in {".", ".."}:
        raise ValueError("library_id_invalid")
    if any(part in {"", ".", ".."} for part in Path(lib).parts):
        raise ValueError("library_id_invalid")
    if "/" in lib or "\\" in lib:
        raise ValueError("library_id_invalid")
    return lib


def resolve_library_workspace(
    library_id: str,
    workspaces_dir: Path,
    *,
    create: bool = False,
    must_exist: bool = True,
) -> Path | None:
    root = Path(workspaces_dir).resolve()
    lib = validate_library_id(library_id)
    target = (root / lib).resolve()

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("library_workspace_outside_root") from exc

    if create:
        target.mkdir(parents=True, exist_ok=True)
    if must_exist and (not target.exists() or not target.is_dir()):
        return None
    return target
