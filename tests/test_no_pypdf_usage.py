from __future__ import annotations

from pathlib import Path
import unittest


class NoPypdfUsageTest(unittest.TestCase):
    def test_repository_does_not_import_pypdf(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        pkg = "py" + "pdf"
        reader_name = "Pdf" + "Reader"
        writer_name = "Pdf" + "Writer"
        for path in repo_root.rglob("*.py"):
            as_posix = path.as_posix()
            if "/.venv/" in as_posix or "/.git/" in as_posix:
                continue
            if path.name == "test_no_pypdf_usage.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if f"from {pkg}" in text or f"import {pkg}" in text or reader_name in text or writer_name in text:
                offenders.append(str(path))

        pyproject = repo_root / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text(encoding="utf-8", errors="ignore")
            if pkg in content:
                offenders.append(str(pyproject))

        self.assertEqual([], offenders, msg=f"{pkg} usage found:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
