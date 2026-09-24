"""
Celery Application Configuration.

Configura Celery com Redis como broker e result backend.
"""

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

from billiard.einfo import ExceptionInfo
from celery import Celery
from celery.result import AsyncResult

# Configuração do broker Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Criar app Celery
celery_app = Celery(
    "review_hub",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.worker.tasks.assessment_tasks",
        "app.worker.tasks.extraction_tasks",
        "app.worker.tasks.import_tasks",
    ],
)

# Configurações
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Result settings
    result_expires=3600,  # 1 hora
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Rate limiting
    task_default_rate_limit="10/m",  # 10 tasks por minuto por default
    # Retry settings
    task_default_retry_delay=60,  # 1 minuto entre retries
    task_max_retries=3,
    # Concurrency
    worker_concurrency=4,
    worker_prefetch_multiplier=2,
    # Task routes (filas separadas por tipo)
    task_routes={
        "app.worker.tasks.assessment_tasks.*": {"queue": "assessments"},
        "app.worker.tasks.extraction_tasks.*": {"queue": "extractions"},
        "app.worker.tasks.import_tasks.*": {"queue": "imports"},
    },
    # Beat scheduler (tarefas periódicas)
    beat_schedule={
        # Exemplo: cleanup de resultados antigos
        "cleanup-old-results": {
            "task": "app.worker.tasks.maintenance_tasks.cleanup_old_results",
            "schedule": 86400.0,  # 24 horas
        },
    },
)


# App-bound Task base class; Celery ships without type hints, so mypy sees it as Any.
_AppTask: Any = celery_app.Task


# Task base class com logging
class LoggedTask(_AppTask):  # type: ignore[misc]  # untyped Celery base class
    """Task base com logging estruturado."""

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        einfo: ExceptionInfo,
    ) -> None:
        """Log em caso de falha."""
        import structlog

        logger = structlog.get_logger()
        logger.error(
            "task_failed",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
            args=args,
            kwargs=kwargs,
        )

    def on_success(
        self,
        retval: Any,
        task_id: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
    ) -> None:
        """Log em caso de sucesso."""
        import structlog

        logger = structlog.get_logger()
        logger.info(
            "task_completed",
            task_id=task_id,
            task_name=self.name,
        )

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        einfo: ExceptionInfo,
    ) -> None:
        """Log em caso de retry."""
        import structlog

        logger = structlog.get_logger()
        logger.warning(
            "task_retry",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
            retry_count=self.request.retries,
        )


# Registrar task base
celery_app.Task = LoggedTask


_P = ParamSpec("_P")
_R = TypeVar("_R")
_R_co = TypeVar("_R_co", covariant=True)


class BoundTask(Protocol[_P, _R_co]):
    """
    Typed view of a Celery task registered with ``bind=True``.

    Celery has no type hints, so this protocol exposes the task API used by the
    application with the signature of the decorated function (without ``self``).
    """

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...

    def delay(self, *args: _P.args, **kwargs: _P.kwargs) -> AsyncResult: ...


class BoundTaskDecorator(Protocol):
    """Decorator returned by :func:`bound_task`."""

    def __call__(self, fun: Callable[Concatenate[LoggedTask, _P], _R], /) -> BoundTask[_P, _R]: ...


def bound_task(**options: Any) -> BoundTaskDecorator:
    """
    Register a function as a bound task, same as ``@celery_app.task(bind=True, **options)``.

    The wrapper only gives the untyped Celery decorator a precise static type, so mypy
    checks the task body and the arguments passed to ``delay``.
    """
    decorator: BoundTaskDecorator = celery_app.task(bind=True, **options)
    return decorator
