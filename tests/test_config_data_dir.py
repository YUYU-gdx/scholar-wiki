"""Tests for kn_graph.config data_dir settings and kn_graph.migration."""

import os
import json
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from kn_graph.config import Settings, ensure_data_dirs, _default_data_dir
from kn_graph.migration import migrate_legacy_data


class TestDataDirDefaults(TestCase):
    def test_default_data_dir_is_path(self):
        s = Settings()
        self.assertIsInstance(s.data_dir, Path)

    def test_default_data_dir_windows_or_home(self):
        result = _default_data_dir()
        self.assertIsInstance(result, Path)
        if os.name == "nt":
            self.assertEqual(str(result), r"D:\KNGraphApp")
        else:
            self.assertTrue(str(result).endswith(".kn_graph"))

    def test_data_dir_overridden_by_env(self):
        tmp = tempfile.mkdtemp()
        try:
            s = Settings(data_dir=Path(tmp))
            self.assertEqual(s.data_dir, Path(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_computed_properties(self):
        tmp = tempfile.mkdtemp()
        try:
            s = Settings(data_dir=Path(tmp))
            self.assertEqual(s.libraries_dir, Path(tmp) / "libraries")
            self.assertEqual(s.workspaces_dir, Path(tmp) / "libraries" / "workspaces")
            self.assertEqual(s.registry_path, Path(tmp) / "libraries" / "registry.json")
            self.assertEqual(s.indexes_dir, Path(tmp) / "libraries" / "indexes")
            self.assertEqual(s.pipeline_db_path, Path(tmp) / "pipeline" / "jobs.sqlite")
            self.assertEqual(s.chat_store_path, Path(tmp) / "chat" / "store.sqlite")
            self.assertEqual(s.workspace_layouts_path, Path(tmp) / "workbench" / "layouts.json")
            self.assertEqual(s.codex_config_path, Path(tmp) / "chat" / "codex_runner_config.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEnsureDataDirs(TestCase):
    def test_creates_all_subdirs(self):
        tmp = tempfile.mkdtemp()
        try:
            s = Settings(data_dir=Path(tmp))
            ensure_data_dirs(s)
            self.assertTrue((Path(tmp)).is_dir())
            self.assertTrue((Path(tmp) / "libraries").is_dir())
            self.assertTrue((Path(tmp) / "libraries" / "workspaces").is_dir())
            self.assertTrue((Path(tmp) / "libraries" / "indexes").is_dir())
            self.assertTrue((Path(tmp) / "pipeline").is_dir())
            self.assertTrue((Path(tmp) / "chat").is_dir())
            self.assertTrue((Path(tmp) / "workbench").is_dir())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_idempotent(self):
        tmp = tempfile.mkdtemp()
        try:
            s = Settings(data_dir=Path(tmp))
            ensure_data_dirs(s)
            ensure_data_dirs(s)
            self.assertTrue((Path(tmp) / "libraries").is_dir())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMigrateLegacyData(TestCase):
    def test_migrates_registry_json(self):
        tmp = tempfile.mkdtemp()
        src = Path(tmp) / "outputs" / "libraries"
        src.mkdir(parents=True)
        registry = src / "registry.json"
        registry.write_text(json.dumps({"version": 1, "libraries": [], "default_library_id": ""}), encoding="utf-8")

        data_dir = Path(tmp) / "data"
        data_dir.mkdir()

        try:
            migrate_legacy_data(data_dir)
            self.assertTrue((data_dir / "libraries" / "registry.json").exists())
            payload = json.loads((data_dir / "libraries" / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_overwrite_existing(self):
        tmp = tempfile.mkdtemp()
        src = Path(tmp) / "outputs" / "libraries"
        src.mkdir(parents=True)
        old_registry = src / "registry.json"
        old_registry.write_text(json.dumps({"version": 1, "libraries": [], "default_library_id": "old"}), encoding="utf-8")

        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        new_reg_dir = data_dir / "libraries"
        new_reg_dir.mkdir()
        new_registry = new_reg_dir / "registry.json"
        new_registry.write_text(json.dumps({"version": 1, "libraries": [], "default_library_id": "new"}), encoding="utf-8")

        try:
            migrate_legacy_data(data_dir)
            payload = json.loads(new_registry.read_text(encoding="utf-8"))
            self.assertEqual(payload["default_library_id"], "new")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_migrates_jobs_db(self):
        tmp = tempfile.mkdtemp()
        src = Path(tmp) / "jobs.db"
        src.write_text("fake_db_content", encoding="utf-8")

        data_dir = Path(tmp) / "data"
        data_dir.mkdir()

        try:
            migrate_legacy_data(data_dir)
            self.assertTrue((data_dir / "pipeline" / "jobs.sqlite").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSettingsKN_GRAPH_DATA_DIR(TestCase):
    def test_env_var_overrides_data_dir(self):
        tmp = tempfile.mkdtemp()
        try:
            original = os.environ.get("KN_GRAPH_DATA_DIR")
            os.environ["KN_GRAPH_DATA_DIR"] = tmp
            try:
                s = Settings()
                self.assertEqual(s.data_dir, Path(tmp))
            finally:
                if original is None:
                    os.environ.pop("KN_GRAPH_DATA_DIR", None)
                else:
                    os.environ["KN_GRAPH_DATA_DIR"] = original
        finally:
            shutil.rmtree(tmp, ignore_errors=True)