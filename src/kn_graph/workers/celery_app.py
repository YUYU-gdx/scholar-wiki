from __future__ import annotations

from celery import Celery

_celery_app: Celery | None = None


def get_celery_app(settings=None) -> Celery:
    global _celery_app
    if _celery_app is not None:
        return _celery_app

    if settings is None:
        from kn_graph.config import Settings
        settings = Settings()
        settings.load_global_settings()

    broker = settings.pipeline_redis_url
    backend_url = broker
    eager = settings.pipeline_executor == "inline"

    if eager:
        broker = "memory://"
        backend_url = "cache+memory://"

    _celery_app = Celery("kn_graph", broker=broker, backend=backend_url)
    _celery_app.conf.update(
        task_always_eager=eager,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
    )
    _celery_app.autodiscover_tasks(["kn_graph.workers"])
    return _celery_app


celery_app = get_celery_app()