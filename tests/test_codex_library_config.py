from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "codex_library_config.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_codex_library_config_tests", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


class CodexLibraryConfigTest(unittest.TestCase):
    def test_bootstrap_workspace_project_skills_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            first = _MOD.bootstrap_workspace_project_skills(str(workspace))
            second = _MOD.bootstrap_workspace_project_skills(str(workspace))
            self.assertGreaterEqual(len(first), 1)
            self.assertEqual(len(first), len(second))
            first_path = Path(str(first[0].get("path", "")))
            self.assertTrue(first_path.exists())
            self.assertTrue((first_path / "SKILL.md").exists())
            self.assertIn(".codex_project_skills", str(first_path))

    def test_bootstrap_library_codex_config_persists_project_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = _MOD.bootstrap_library_codex_config(str(workspace), library_id="lib_a")
            self.assertEqual(payload.get("library_id"), "lib_a")
            project_skills = payload.get("project_skills", [])
            self.assertTrue(isinstance(project_skills, list))
            self.assertGreaterEqual(len(project_skills), 1)
            cfg_path = _MOD.config_path_for_workspace(str(workspace))
            self.assertTrue(cfg_path.exists())


if __name__ == "__main__":
    unittest.main()
