from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import importlib.util
import sys


_MOD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "library_registry.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_library_registry_test", _MOD_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load module: {_MOD_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


class LibraryRegistryCreateTest(unittest.TestCase):
    def test_create_library_writes_registry_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = root / "registry.json"
            idx = root / "indexes"
            ws_base = root / "workspaces"
            ws_base.mkdir(parents=True, exist_ok=True)

            result = _MOD.create_library(
                library_id="supply_chain",
                registry_path=reg,
                legacy_index_root=idx,
                workspace_root=str(ws_base / "supply_chain"),
                set_default=True,
            )

            self.assertEqual(result["library_id"], "supply_chain")
            self.assertTrue((idx / "supply_chain.json").exists())
            self.assertTrue((ws_base / "supply_chain").exists())

            payload = json.loads(reg.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("default_library_id"), "supply_chain")
            libs = payload.get("libraries", [])
            self.assertTrue(any(str(x.get("library_id", "")) == "supply_chain" for x in libs if isinstance(x, dict)))

    def test_create_library_supports_cjk_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = root / "registry.json"
            idx = root / "indexes"
            ws_base = root / "workspaces"
            ws_base.mkdir(parents=True, exist_ok=True)
            _MOD.configure(workspace_root=ws_base, registry_path=reg, index_root=idx)

            result = _MOD.create_library(
                library_id="供应链",
                registry_path=reg,
                legacy_index_root=idx,
                workspace_root="",
                set_default=True,
            )
            self.assertEqual(result["library_id"], "供应链")
            self.assertTrue((idx / "供应链.json").exists())
            self.assertTrue((ws_base / "供应链").exists())

    def test_delete_library_removes_registry_index_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = root / "registry.json"
            idx = root / "indexes"
            ws_base = root / "workspaces"
            ws_base.mkdir(parents=True, exist_ok=True)
            _MOD.configure(workspace_root=ws_base, registry_path=reg, index_root=idx)

            _MOD.create_library(
                library_id="lib_a",
                registry_path=reg,
                legacy_index_root=idx,
                workspace_root=str(ws_base / "lib_a"),
                set_default=True,
            )
            _MOD.create_library(
                library_id="lib_b",
                registry_path=reg,
                legacy_index_root=idx,
                workspace_root=str(ws_base / "lib_b"),
                set_default=False,
            )
            self.assertTrue((idx / "lib_a.json").exists())
            self.assertTrue((ws_base / "lib_a").exists())

            out = _MOD.delete_library(
                library_id="lib_a",
                registry_path=reg,
                legacy_index_root=idx,
                delete_workspace_data=True,
            )
            self.assertTrue(out.get("deleted"))
            self.assertFalse((idx / "lib_a.json").exists())
            self.assertFalse((ws_base / "lib_a").exists())

            payload = json.loads(reg.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("default_library_id"), "lib_b")
            libs = payload.get("libraries", [])
            self.assertFalse(any(str(x.get("library_id", "")) == "lib_a" for x in libs if isinstance(x, dict)))


if __name__ == "__main__":
    unittest.main()
