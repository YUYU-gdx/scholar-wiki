from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_FILE_ACCESS_MARKERS = (
    "windows cannot access the specified device, path, or file",
    "windows cannot access",
    "winerror 5",
    "permission denied",
    "access is denied",
    "file not found",
    "path not found",
    "cannot find the file",
    "no such file or directory",
)


def _looks_like_windows_path(path_text: str) -> bool:
    text = str(path_text or "").strip()
    if not text:
        return False
    return text.startswith("\\\\") or (len(text) >= 3 and text[1:3] in {":\\", ":/"})


def _looks_like_shared_or_vm_path(path_text: str) -> bool:
    text = str(path_text or "").strip().lower()
    if not text:
        return False
    return text.startswith("\\\\") or any(
        marker in text
        for marker in (
            "vboxsvr",
            "vmware-host",
            "onedrive",
            "share",
            "shared",
        )
    )


def _path_probe(path_value: str | Path | None) -> dict[str, Any]:
    text = str(path_value or "").strip()
    out: dict[str, Any] = {
        "path": text,
        "exists": False,
        "is_file": False,
        "is_dir": False,
        "parent_exists": False,
        "error": "",
    }
    if not text:
        return out
    try:
        p = Path(text)
        out["exists"] = p.exists()
        out["is_file"] = p.is_file()
        out["is_dir"] = p.is_dir()
        out["parent_exists"] = p.parent.exists()
        try:
            out["resolved"] = str(p.resolve())
        except OSError:
            out["resolved"] = str(p)
    except OSError as exc:
        out["error"] = str(exc)
    return out


def should_add_file_access_diagnostics(detail: str, source_path: str = "") -> bool:
    haystack = f"{detail}\n{source_path}".lower()
    return any(marker in haystack for marker in _FILE_ACCESS_MARKERS)


def append_file_access_diagnostics(detail: str, source_path: str | Path = "") -> str:
    base = str(detail or "").strip()
    path_text = str(source_path or "").strip()
    if not should_add_file_access_diagnostics(base, path_text):
        return base
    if "File access diagnostics:" in base:
        return base

    lines = ["", "File access diagnostics:"]
    if path_text:
        lines.append(f"- Source path: {path_text}")
    lines.append('- In the VM PowerShell, run: Test-Path -LiteralPath "the full path above"')
    lines.append("- If Test-Path is False, the path is not visible inside the VM or is a stale/temp/source path.")
    lines.append("- If Test-Path is True, check backend process permissions, file locks, and Windows Defender controlled folder access.")
    if path_text and _looks_like_windows_path(path_text):
        lines.append("- Try copying the file to a short VM-local path such as C:\\kn-test\\paper.pdf and import again.")
    if path_text and _looks_like_shared_or_vm_path(path_text):
        lines.append("- This looks like a shared/synced path; check share mapping and permissions first.")
    return base + "\n" + "\n".join(lines)


def build_import_path_diagnostics(
    *,
    data_dir: str | Path = "",
    workspaces_dir: str | Path = "",
    library_id: str = "",
    workspace_path: str | Path = "",
    runs_root: str | Path = "",
    run_dir: str | Path = "",
    input_path: str | Path = "",
    source_path: str | Path = "",
    extra_paths: dict[str, str | Path] | None = None,
) -> dict[str, Any]:
    paths: dict[str, Any] = {
        "data_dir": _path_probe(data_dir),
        "workspaces_dir": _path_probe(workspaces_dir),
        "workspace_path": _path_probe(workspace_path),
        "runs_root": _path_probe(runs_root),
        "run_dir": _path_probe(run_dir),
        "input_path": _path_probe(input_path),
        "source_path": _path_probe(source_path),
    }
    for name, value in (extra_paths or {}).items():
        paths[str(name)] = _path_probe(value)
    return {
        "kind": "import_path_diagnostics",
        "library_id": str(library_id or "").strip(),
        "cwd": os.getcwd(),
        "python_executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "env": {
            "KN_GRAPH_DATA_DIR": os.getenv("KN_GRAPH_DATA_DIR", ""),
            "KN_GRAPH_WORKSPACES_DIR": os.getenv("KN_GRAPH_WORKSPACES_DIR", ""),
            "LITERATURE_LIBRARY_WORKSPACES_ROOT": os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", ""),
            "APPDATA": os.getenv("APPDATA", ""),
            "LOCALAPPDATA": os.getenv("LOCALAPPDATA", ""),
        },
        "paths": paths,
    }
