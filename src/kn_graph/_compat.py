"""Compatibility helpers for PyInstaller frozen environments.

All path resolution should go through this module so that bundled data
files are found under both ``sys._MEIPASS`` (PyInstaller) and the
normal project root (development).
"""
from __future__ import annotations

import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, 'frozen', False)


def _frozen_root() -> Path:
    return Path(sys._MEIPASS)


def _project_root() -> Path:
    # _compat.py lives at src/kn_graph/_compat.py
    # parents[0] = src/kn_graph/_compat.py
    # parents[1] = src/kn_graph/
    # parents[2] = src/
    # parents[3] = project root
    return Path(__file__).resolve().parents[3]


def bundle_root() -> Path:
    """Root directory for locating bundled data files.

    Under PyInstaller: ``sys._MEIPASS`` (the ``_internal/`` directory).
    Under normal Python: the project root directory.
    """
    if _is_frozen():
        return _frozen_root()
    return _project_root()


def get_data_path(relative_path: str) -> Path:
    """Resolve a data file path relative to the bundle root."""
    return bundle_root() / relative_path
