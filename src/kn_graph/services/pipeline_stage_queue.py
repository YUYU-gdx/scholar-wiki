from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any, Callable

from kn_graph.config import Settings
from kn_graph.services.pipeline_service import PipelineService

StageHandler = Callable[[dict[str, Any], Callable[[], None]], dict[str, Any] | None]


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, int(raw))
    except Exception:
        return max(minimum, default)


class StageQueueWorker:
    """Single-stage worker loop with lease heartbeat and retry-aware failure.

    The hard cap for `paper_extract` is enforced at claim-time by the store.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        stage: str,
        handler: StageHandler,
        worker_tag: str = "",
    ) -> None:
        self._settings = settings
        self._stage = str(stage or "").strip().lower()
        self._handler = handler
        self._service = PipelineService(settings)
        host = socket.gethostname()
        pid = os.getpid()
        tid = threading.get_ident()
        suffix = str(worker_tag or "").strip()
        self._worker_id = f"{host}:{pid}:{tid}:{self._stage}{(':' + suffix) if suffix else ''}"
        self._stop = threading.Event()

        self._lease_seconds = _env_int("PIPELINE_STAGE_LEASE_SECONDS", 120, minimum=30)
        self._idle_sleep_seconds = _env_int("PIPELINE_STAGE_IDLE_SLEEP_SECONDS", 2, minimum=1)
        self._extract_limit = _env_int("PIPELINE_CONCURRENCY_EXTRACT", 3, minimum=1)

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self._service.requeue_stale_stage_tasks()
            except Exception:
                pass

            task = self._service.claim_stage_task(
                self._stage,
                self._worker_id,
                lease_seconds=self._lease_seconds,
                extract_limit=self._extract_limit,
            )
            if not isinstance(task, dict):
                time.sleep(self._idle_sleep_seconds)
                continue

            task_id = str(task.get("id", "") or "")
            hb_stop = threading.Event()
            hb_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(task_id, hb_stop),
                daemon=True,
            )
            hb_thread.start()
            try:
                out = self._handler(task, lambda: self._stop.is_set())
                ok = self._service.complete_stage_task(task_id, self._worker_id, output_json=out or {})
                if not ok:
                    self._service.fail_stage_task(
                        task_id,
                        self._worker_id,
                        "stage_complete_conflict",
                        "failed to mark task as completed",
                        retryable=True,
                    )
            except Exception as exc:
                self._service.fail_stage_task(
                    task_id,
                    self._worker_id,
                    "stage_execution_failed",
                    str(exc),
                    retryable=True,
                )
            finally:
                hb_stop.set()
                hb_thread.join(timeout=2.0)

    def _heartbeat_loop(self, task_id: str, stop_evt: threading.Event) -> None:
        interval = max(10, int(self._lease_seconds / 3))
        while not stop_evt.wait(interval):
            self._service.heartbeat_stage_task(task_id, self._worker_id, lease_seconds=self._lease_seconds)


def start_stage_pool(
    *,
    settings: Settings,
    stage: str,
    handler: StageHandler,
    concurrency: int,
    worker_tag: str = "",
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    total = max(1, int(concurrency))
    for idx in range(total):
        worker = StageQueueWorker(
            settings=settings,
            stage=stage,
            handler=handler,
            worker_tag=f"{worker_tag}-{idx}",
        )
        t = threading.Thread(target=worker.run_forever, name=f"stage-worker-{stage}-{idx}", daemon=True)
        t.start()
        threads.append(t)
    return threads

