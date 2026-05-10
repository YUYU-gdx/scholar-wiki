from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class ClassifyBaseDatasetABCTest(unittest.TestCase):
    def test_classify_base_dataset_outputs_a_b_c_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            html_a = tmp / "a.html"
            html_a.write_text(
                "<html><body><h2>Introduction</h2><h2>Methods</h2><h2>Results</h2><table><tr><td>beta=0.3 p<0.05</td></tr></table></body></html>",
                encoding="utf-8",
            )
            html_b = tmp / "b.html"
            html_b.write_text("<html><body><h2>Abstract</h2><h2>References</h2></body></html>", encoding="utf-8")
            html_c = tmp / "c.html"
            html_c.write_text("<html><body><h2>Editorial Note</h2></body></html>", encoding="utf-8")

            base_jsonl = tmp / "base_dataset.jsonl"
            rows = [
                {"paper_id": "p-a", "normalized_html_path": str(html_a)},
                {"paper_id": "p-b", "normalized_html_path": str(html_b)},
                {"paper_id": "p-c", "normalized_html_path": str(html_c)},
            ]
            base_jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

            out_dir = tmp / "class_abc"
            cmd = [
                "uv",
                "run",
                "python",
                "src/kn_graph/services/classify_base_dataset_abc.py",
                "--input-base-dataset",
                str(base_jsonl),
                "--output-dir",
                str(out_dir),
            ]
            proc = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

            summary = json.loads((out_dir / "classification_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["total_rows"], 3)
            self.assertEqual(summary["class_a_rows"], 1)
            self.assertEqual(summary["class_b_rows"], 1)
            self.assertEqual(summary["class_c_rows"], 1)
            self.assertTrue((out_dir / "base_dataset_class_a.jsonl").exists())
            self.assertTrue((out_dir / "base_dataset_class_b.jsonl").exists())
            self.assertTrue((out_dir / "base_dataset_class_c.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
