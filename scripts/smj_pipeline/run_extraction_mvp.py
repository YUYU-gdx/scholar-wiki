from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Iterable, Iterator


def _load_sibling_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_QUALIFIER_MOD = _load_sibling_module(
    "smj_pipeline_extraction_qualifier",
    "extraction/qualifier.py",
)
classify_document = _QUALIFIER_MOD.classify_document


@dataclass(slots=True, eq=True)
class RunSummary:
    seen: int
    class_a_used: int
    class_b_skipped: int
    class_c_skipped: int
    denominator_used: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def run(input_manifest: Path | str | Iterable[dict[str, object]], sample_size: int = 100) -> RunSummary:
    if sample_size < 0:
        raise ValueError("sample_size must be non-negative")

    seen = 0
    class_a_used = 0
    class_b_skipped = 0
    class_c_skipped = 0
    denominator_used = 0

    for row in _iter_manifest_rows(input_manifest):
        if class_a_used >= sample_size:
            break

        seen += 1
        html = str(row.get("html", ""))
        qualification = classify_document(html)
        doc_class = getattr(qualification, "doc_class", "C")

        if doc_class == "B":
            class_b_skipped += 1
            continue

        denominator_used += 1
        if doc_class == "A":
            class_a_used += 1
            _process_class_a_record(row)
        else:
            class_c_skipped += 1

    return RunSummary(
        seen=seen,
        class_a_used=class_a_used,
        class_b_skipped=class_b_skipped,
        class_c_skipped=class_c_skipped,
        denominator_used=denominator_used,
    )


def _iter_manifest_rows(
    input_manifest: Path | str | Iterable[dict[str, object]],
) -> Iterator[dict[str, object]]:
    if isinstance(input_manifest, (str, Path)):
        path = Path(input_manifest)
        with path.open("r", encoding="utf-8") as handle:
            yield from _iter_jsonl_lines(handle)
        return

    for row in input_manifest:
        yield dict(row)


def _iter_jsonl_lines(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    for line in lines:
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("manifest rows must be JSON objects")
        yield payload


def _process_class_a_record(row: dict[str, object]) -> None:
    # Placeholder orchestration hook for later extraction/storage wiring.
    _ = row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run extraction MVP over a local manifest JSONL.")
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--sample-size", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run(args.input_manifest, sample_size=args.sample_size)
    print(json.dumps(summary.to_dict(), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
