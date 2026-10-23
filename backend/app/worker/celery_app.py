"""
Celery Application Configuration.

Configures Celery with Redis as broker and result backend.
"""

from typing import Any

from celery import Celery

from app.core.config import settings

# Create the Celery app
celery_app = Celery(
    "review_hub",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.worker.tasks.extraction_tasks",
        "app.worker.tasks.extraction_batch_tasks",
        "app.worker.tasks.import_tasks",
        "app.worker.tasks.export_tasks",
        "app.worker.tasks.extraction_export_tasks",
        "app.worker.tasks.feedback_tasks",
        "app.worker.tasks.parsing_tasks",
    ],
)

# Configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Result settings
    result_expires=3600,  # 1 hour
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Rate limiting
    task_default_rate_limit="10/m",  # 10 tasks per minute by default
    # Retry settings
    task_default_retry_delay=60,  # 1 minute between retries
    task_max_retries=3,
    # Concurrency. Railway bills resident RAM, and every prefork child imports
    # the whole app, so idle children cost money around the clock. Tasks are
    # I/O-bound (LLM/HTTP) and rate-limited to 10/m, so 2 children suffice.
    worker_concurrency=2,
    # Recycle a child once it exceeds ~400 MB (KiB; checked after each task)
    # so memory grown during a heavy PDF/LLM task is returned.
    worker_max_memory_per_child=400_000,
    worker_prefetch_multiplier=2,
    # Redis visibility timeout. With task_acks_late=True, an in-flight message
    # stays "invisible" only this long before Redis redelivers it. The
    # invariant: it MUST exceed every task's hard time_limit, or a still-running
    # task gets redelivered and runs twice (the classic Celery+Redis duplicate-
    # execution footgun). 3600s is the library default, made explicit here so it
    # can't silently fall below a task limit; the bounded parse task (hard 360s)
    # sits well under it.
    broker_transport_options={"visibility_timeout": 3600},
    # Task routes (queues separated by type). Every module in
    # ``include=`` MUST appear here explicitly — the registry test in
    # ``tests/unit/test_celery_app_task_registry.py`` enforces this so
    # new task modules cannot silently fall back to the default
    # ``celery`` queue (which the Railway worker may or may not be
    # consuming). The drift guard
    # ``tests/unit/test_celery_routes_drift.py`` then asserts every
    # queue named here is in the worker ``--queues=...`` list.
    task_routes={
        "app.worker.tasks.extraction_tasks.*": {"queue": "extractions"},
        # AI batch dispatcher: no LLM work, but it hands jobs to the
        # extraction queue, so it lives beside them.
        "app.worker.tasks.extraction_batch_tasks.*": {"queue": "extractions"},
        "app.worker.tasks.import_tasks.*": {"queue": "imports"},
        # Keep CPU-bound XLSX builds off the LLM-heavy `extractions` queue
        # so a long-running extraction can't starve a user-initiated export.
        "app.worker.tasks.extraction_export_tasks.*": {"queue": "exports"},
        # Article exports (CSV/RIS/RDF + ZIP) — explicit `celery` queue so
        # the drift guard has a clean baseline. The Railway worker
        # consumes `celery` alongside the three named queues.
        "app.worker.tasks.export_tasks.*": {"queue": "celery"},
        # Feedback forwarding to Linear — low-volume, no special resource
        # requirements, routed to the already-consumed `celery` queue.
        "app.worker.tasks.feedback_tasks.*": {"queue": "celery"},
        # PDF parsing at ingest — routed to the `celery` queue; low initial
        # volume, no separate queue needed until throughput warrants it.
        "app.worker.tasks.parsing_tasks.*": {"queue": "celery"},
    },
)


# Task base class with logging
class LoggedTask(celery_app.Task):
    """Task base class with structured logging."""

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        _einfo: Any,
    ) -> None:
        """Log on failure."""
        import structlog
        from celery.exceptions import NotRegistered

        logger = structlog.get_logger()
        if isinstance(exc, NotRegistered):
            # P1-class incident: an enqueued task has no handler. Always
            # caused by a module missing from celery_app.include or a
            # routing typo. Surface separately so dashboards can alert.
            logger.error(
                "celery.task_unregistered",
                task_id=task_id,
                task_name=self.name,
                args=args,
                kwargs=kwargs,
                remediation=(
                    "Check celery_app.include for the missing module and "
                    "tests/unit/test_celery_app_task_registry.py for the "
                    "regression guard."
                ),
            )
            return
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
        _retval: Any,
        task_id: str,
        _args: tuple[Any, ...],
        _kwargs: dict[str, Any],
    ) -> None:
        """Log on success."""
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
        _args: tuple[Any, ...],
        _kwargs: dict[str, Any],
        _einfo: Any,
    ) -> None:
        """Log on retry."""
        import structlog

        logger = structlog.get_logger()
        logger.warning(
            "task_retry",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
            retry_count=self.request.retries,
        )


# Register the base task class
celery_app.Task = LoggedTask


# Register a signal handler for tasks that the worker receives but
# cannot find in its registry. Celery routes this through the consumer
# (signals.task_unknown), not the task instance's on_failure callback —
# so a NotRegistered branch in on_failure alone would be dead code in
# production. Keep both paths: the signal is the runtime hook, the
# on_failure branch is defense in depth in case Celery changes routing.
from celery.signals import task_unknown, worker_init, worker_process_init  # noqa: E402


@worker_init.connect(weak=False)
def _refuse_placeholder_encryption_key(**_kwargs: Any) -> None:
    """Stop the worker before it forks if ``ENCRYPTION_KEY`` is the placeholder.

    Runs in the parent (``worker_init``): a SystemExit in a forked child would
    only make the parent respawn it. Celery's signal dispatch catches
    ``Exception``, not ``SystemExit``, so the exit reaches the worker boot.
    """
    from app.core.security import check_encryption_key

    check_encryption_key()


@worker_process_init.connect(weak=False)
def _configure_worker_observability(**_kwargs: Any) -> None:
    """Logfire + logging bootstrap for each forked worker child.

    Must run post-fork (``worker_process_init``, not ``worker_init``):
    BatchSpanProcessor's export thread does not survive the prefork
    fork, so configuring in the parent silently drops every task span.
    Lazy imports keep the API process (which imports this module for
    ``.delay()``) free of worker-side configuration.
    """
    from app.core.logging import configure_logging
    from app.llm.observability import configure_observability

    configure_observability(service_name="prumo-worker")
    configure_logging()


@task_unknown.connect
def _on_task_unknown(
    # Celery passes every kwarg below positionally-by-name; the signature
    # must accept them even where the handler ignores the value.
    sender: Any = None,  # noqa: ARG001
    name: str | None = None,
    id: str | None = None,  # noqa: A002 — Celery signal kwarg name
    message: Any = None,  # noqa: ARG001
    exc: Exception | None = None,  # noqa: ARG001
    **_kwargs: Any,
) -> None:
    """Log unregistered-task events as a P1 incident.

    Triggered by Celery when a worker pops a message whose ``task``
    header does not match any entry in ``celery_app.tasks``. Always
    caused by a module missing from ``celery_app.include`` or a routing
    typo. The regression guard at
    ``tests/unit/test_celery_app_task_registry.py`` prevents this at CI,
    and the drift guard at ``tests/unit/test_celery_routes_drift.py``
    prevents queue/route mismatches; this signal is the runtime safety
    net.
    """
    import structlog

    structlog.get_logger().error(
        "celery.task_unregistered",
        task_id=id,
        task_name=name,
        remediation=(
            "Check celery_app.include for the missing module and "
            "tests/unit/test_celery_app_task_registry.py for the "
            "regression guard."
        ),
    )
