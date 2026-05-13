from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from kn_graph.services.codex_library_config import (
    bootstrap_workspace_project_skills,
    bootstrap_library_codex_config,
    config_path_for_workspace,
)


class CodexLibraryConfigTest(unittest.TestCase):
    def test_bootstrap_workspace_project_skills_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            first = bootstrap_workspace_project_skills(str(workspace))
            second = bootstrap_workspace_project_skills(str(workspace))
            self.assertGreaterEqual(len(first), 2)  # at least .claude + .agents
            self.assertEqual(len(first), len(second))
            # Verify both backends get deployed
            paths = [str(p.get("path", "")) for p in first]
            claude_paths = [p for p in paths if ".claude" in p]
            agents_paths = [p for p in paths if ".agents" in p]
            self.assertGreaterEqual(len(claude_paths), 1)
            self.assertGreaterEqual(len(agents_paths), 1)
            for p in first:
                skill_dir = Path(str(p.get("path", "")))
                self.assertTrue(skill_dir.exists())
                self.assertTrue((skill_dir / "SKILL.md").exists())
            # Agent markdown templates should be synchronized with skill bootstrap timing.
            self.assertTrue((workspace / "CLAUDE.md").exists())
            self.assertTrue((workspace / "AGENTS.md").exists())
            # Legacy path should be cleaned up
            self.assertFalse((workspace / ".codex_project_skills").exists())

    def test_bootstrap_library_codex_config_persists_project_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = bootstrap_library_codex_config(str(workspace), library_id="lib_a")
            self.assertEqual(payload.get("library_id"), "lib_a")
            project_skills = payload.get("project_skills", [])
            self.assertTrue(isinstance(project_skills, list))
            self.assertGreaterEqual(len(project_skills), 2)  # at least .claude + .agents
            cfg_path = config_path_for_workspace(str(workspace))
            self.assertTrue(cfg_path.exists())


if __name__ == "__main__":
    unittest.main()
