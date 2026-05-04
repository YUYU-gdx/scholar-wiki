from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from kn_graph.config import Settings

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"


def _load_literature_service_class():
    module_path = _SCRIPTS_DIR / "literature" / "service.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_literature_service_for_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.LiteratureService


def _load_library_registry_module():
    module_path = _SCRIPTS_DIR / "library_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_library_registry_for_literature_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LiteratureService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: Any = None

    def _ensure_service(self) -> Any:
        if self._service is not None:
            return self._service
        cls = _load_literature_service_class()
        self._service = cls()
        return self._service

    def search(
        self,
        query: str,
        top_k: int = 20,
        levels: list[str] | None = None,
        library_id: str = "",
        keyword_weight: float = 0.4,
        rag_weight: float = 0.6,
        include_expanded_context: bool = True,
    ) -> dict[str, Any]:
        if levels is None:
            levels = ["sentence"]
        literature = self._ensure_service()
        return literature.search(
            query=query,
            top_k=top_k,
            levels=levels,
            library_id=library_id,
            keyword_weight=keyword_weight,
            rag_weight=rag_weight,
            include_expanded_context=include_expanded_context,
        )

    def answer(
        self,
        query: str,
        top_k: int = 5,
        levels: list[str] | None = None,
        library_id: str = "",
        keyword_weight: float = 0.4,
        rag_weight: float = 0.6,
    ) -> dict[str, Any]:
        if levels is None:
            levels = ["sentence"]
        literature = self._ensure_service()
        return literature.answer(
            query=query,
            top_k=top_k,
            levels=levels,
            library_id=library_id,
            keyword_weight=keyword_weight,
            rag_weight=rag_weight,
        )

    def list_libraries(self) -> dict[str, Any]:
        try:
            reg_mod = _load_library_registry_module()
            index_root = self._settings.indexes_dir
            registry = reg_mod.ensure_registry(
                registry_path=self._settings.registry_path,
                legacy_index_root=index_root,
            )
            return reg_mod.list_libraries_payload(registry)
        except Exception:
            return {"libraries": [], "default_library_id": ""}

    def import_manifest(self, manifest_path: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if options is None:
            options = {}
        literature = self._ensure_service()
        return literature.import_manifest(manifest_path=manifest_path, options=options)

    def create_library(self, library_id: str, workspace_root: str = "", set_default: bool = True) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        reg_mod = _load_library_registry_module()
        return reg_mod.create_library(
            library_id=lib,
            registry_path=self._settings.registry_path,
            legacy_index_root=self._settings.indexes_dir,
            workspace_root=str(workspace_root or "").strip(),
            set_default=bool(set_default),
        )

    def delete_library(self, library_id: str, delete_workspace_data: bool = True) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        reg_mod = _load_library_registry_module()
        return reg_mod.delete_library(
            library_id=lib,
            registry_path=self._settings.registry_path,
            legacy_index_root=self._settings.indexes_dir,
            delete_workspace_data=bool(delete_workspace_data),
        )
