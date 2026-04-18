from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True)
class ReviewQueueItem:
    record: dict[str, Any]
    reason_codes: list[str]


@dataclass(slots=True)
class ReviewQueue:
    items: list[ReviewQueueItem]

    @property
    def total_items(self) -> int:
        return len(self.items)


def build_review_queue(rejected_records: Iterable[object]) -> ReviewQueue:
    items = [
        ReviewQueueItem(
            record=dict(getattr(item, "record")),
            reason_codes=list(getattr(item, "reason_codes")),
        )
        for item in rejected_records
    ]
    return ReviewQueue(items=items)


def write_review_queue_jsonl(queue: ReviewQueue, output_path: str | Path) -> None:
    output = Path(output_path)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for item in queue.items:
            payload = {
                "reason_codes": list(item.reason_codes),
                "record": dict(sorted(item.record.items())),
            }
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            handle.write("\n")


def write_review_queue_csv(queue: ReviewQueue, output_path: str | Path) -> None:
    output = Path(output_path)
    fieldnames = [
        "reason_codes",
        "paper_id",
        "source",
        "target",
        "direction",
        "relation_form",
        "verification",
        "evidence_section",
        "hypothesis_label",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in queue.items:
            writer.writerow(
                {
                    "reason_codes": "|".join(item.reason_codes),
                    "paper_id": item.record.get("paper_id", ""),
                    "source": item.record.get("source", ""),
                    "target": item.record.get("target", ""),
                    "direction": item.record.get("direction", ""),
                    "relation_form": item.record.get("relation_form", ""),
                    "verification": item.record.get("verification", ""),
                    "evidence_section": item.record.get("evidence_section", ""),
                    "hypothesis_label": item.record.get("hypothesis_label", ""),
                }
            )
