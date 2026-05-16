from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _project_root() -> Path:
    # .../src/kn_graph/services/mcp_launch.py -> repo root
    return Path(__file__).resolve().parents[3]


def default_mcp_server_command_and_args() -> tuple[str, list[str]]:
    """Return stable MCP launcher command for current runtime mode.

    Frozen build: launch from current executable path (absolute).
    Dev/source: launch via uv with explicit --project absolute path.
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ["mcp-server"]

    uv_bin = shutil.which("uv") or "uv"
    return uv_bin, [
        "run",
        "--project",
        str(_project_root()),
        "python",
        "-m",
        "kn_graph.services.kn_mcp_server",
    ]


def default_mcp_server_args() -> list[str]:
    _cmd, args = default_mcp_server_command_and_args()
    return args
