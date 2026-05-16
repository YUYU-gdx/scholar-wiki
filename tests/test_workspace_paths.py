from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kn_graph.services.literature_service import LiteratureService
from kn_graph.services.workspace_paths import resolve_library_workspace


class TestWorkspacePaths(unittest.TestCase):
    def test_resolves_library_workspace_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspaces'
            target = resolve_library_workspace('lib_a', root, create=True)

            self.assertEqual(target, (root / 'lib_a').resolve())
            self.assertTrue(target.is_dir())

    def test_rejects_path_traversal_library_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspaces'

            with self.assertRaises(ValueError):
                resolve_library_workspace('../outside', root, create=True)

            self.assertFalse((Path(tmp) / 'outside').exists())

    def test_rejects_nested_path_library_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspaces'

            with self.assertRaises(ValueError):
                resolve_library_workspace('group/lib_a', root, create=True)

    def test_missing_workspace_returns_none_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspaces'

            self.assertIsNone(resolve_library_workspace('missing', root, must_exist=True))

    def test_literature_create_library_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = type(
                'S',
                (),
                {
                    'workspaces_dir': root / 'workspaces',
                    'indexes_dir': root / 'indexes',
                },
            )()
            service = LiteratureService(settings=settings)

            with self.assertRaises(ValueError):
                service.create_library('../outside')

            self.assertFalse((root / 'outside').exists())

    def test_literature_delete_library_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside'
            outside.mkdir()
            marker = outside / 'keep.txt'
            marker.write_text('keep', encoding='utf-8')
            settings = type(
                'S',
                (),
                {
                    'workspaces_dir': root / 'workspaces',
                    'indexes_dir': root / 'indexes',
                },
            )()
            service = LiteratureService(settings=settings)

            with self.assertRaises(ValueError):
                service.delete_library('../outside')

            self.assertTrue(marker.exists())


if __name__ == '__main__':
    unittest.main()
