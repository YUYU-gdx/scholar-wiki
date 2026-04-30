from __future__ import annotations

import os

from celery import Celery


def _build_celery_app() -> Celery:
    broker = os.getenv("KN_GRAPH_PIPELINE_REDIS_URL", os.getenv("PIPELINE_REDIS_URL", "redis://127.0.0.1:6379/0")).strip()
    backend_url = os.getenv("KN_GRAPH_CELERY_BACKEND", broker).strip()

    eager = os.getenv("PIPELINE_TASK_ALWAYS_EAGER", "").strip().lower() in {"1", "true", "yes", "on"}
    if eager:
        broker = "memory://"
        backend_url = "cache+memory://"

    app = Celery("kn_graph", broker=broker, backend=backend_url)
    app.conf.update(
        task_always_eager=eager,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
    )

    app.autodiscover_tasks(["kn_graph.workers"])

    return app


celery_app = _build_celery_app()