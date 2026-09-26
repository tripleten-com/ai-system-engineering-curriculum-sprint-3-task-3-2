"""Coldline.

===================

File:              src/worker/bootstrap.py
Component:         Worker — Bootstrap
Purpose:           Compose and run the Redis-backed Coldline worker.
Interacts With:    Redis Streams, domain, ports, and adapters
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Background processing, retries, idempotency
Tools:             Python 3.12, PostgreSQL, Redis, OpenTelemetry, Prometheus
"""

import asyncio
import logging
import signal
from datetime import UTC, datetime

import asyncpg
from opentelemetry import trace
from opentelemetry.instrumentation.redis import RedisInstrumentor
from prometheus_client import start_http_server
from redis.asyncio import Redis

from adapters.logging import configure_json_logging
from adapters.model import DeterministicModelProvider, ResilientModelProvider
from adapters.persistence import PostgresExceptionRepository
from adapters.queue import RedisJobQueue
from adapters.telemetry import configure_tracing
from ports import ModelProvider
from worker.config import WorkerSettings
from worker.runtime import run_loop
from worker.use_cases import WorkerApplication


def build_model_provider(settings: WorkerSettings) -> ModelProvider:
    """Return the model provider the worker calls for each summary.

    The deterministic emulator is wrapped in the supplied
    ``ResilientModelProvider`` so every attempt is bounded by its own timeout
    and the attempt budget stays bounded too. The three bounds come from
    settings, which hold them in milliseconds; the wrapper takes seconds.
    """
    return ResilientModelProvider(
        DeterministicModelProvider(latency_ms=settings.model_latency_ms),
        timeout_seconds=settings.model_timeout_ms / 1000,
        max_attempts=settings.model_provider_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000,
    )


async def run() -> None:
    """Compose the worker, run it, and release every owned resource.

    This is wiring only. Domain decisions stay in ``WorkerApplication`` and
    provider behavior stays behind ports. Signal handlers cancel the loop, then
    the ``finally`` block closes Redis, PostgreSQL, and the trace provider.
    """
    settings = WorkerSettings()  # type: ignore[call-arg]  # protected environment is the source
    configure_json_logging(settings.service_name)
    logging.getLogger(__name__).info("worker starting build_version=%s", settings.build_version)
    tracer_provider = configure_tracing(settings.service_name, settings.otel_endpoint)
    RedisInstrumentor().instrument()
    tracer = trace.get_tracer(__name__)
    pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=4)
    redis = Redis.from_url(settings.redis_url)
    queue = RedisJobQueue(
        redis,
        stream=settings.stream_name,
        group=settings.consumer_group,
        consumer=settings.consumer_name,
    )
    await queue.initialize()
    start_http_server(settings.metrics_port)
    application = WorkerApplication(
        PostgresExceptionRepository(pool),
        build_model_provider(settings),
        clock=lambda: datetime.now(UTC),
        maximum_attempts=settings.maximum_attempts,
    )
    worker_task = asyncio.create_task(
        run_loop(queue, application, tracer, stale_message_ms=settings.stale_message_ms)
    )
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(shutdown_signal, worker_task.cancel)
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    finally:
        await redis.aclose()
        await pool.close()
        tracer_provider.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
