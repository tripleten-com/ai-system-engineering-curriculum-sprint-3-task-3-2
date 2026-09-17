"""Coldline.

===================

File:              tests/contract/runtime_adapters.py
Component:         Contract tests — Runtime Adapters
Purpose:           Exercise PostgreSQL and Redis adapter behavior against the running stack.
Interacts With:    Published interfaces and repository boundaries
Sprint/Task:       Sprint 1 — Project 1
Concepts:          Compatibility, ownership, export safety
Tools:             Python 3.12, pytest, PostgreSQL, Redis
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
from redis.asyncio import Redis

from adapters.persistence import PostgresExceptionRepository
from adapters.queue import RedisJobQueue
from domain.contracts import (
    ExceptionJob,
    ExceptionRecord,
    ExceptionState,
    ModelRequest,
    ModelSummary,
    SensorReading,
)
from worker.use_cases import ProcessingDisposition, WorkerApplication

DATABASE_URL = "postgresql://coldline:coldline_local@postgres:5432/coldline"
REDIS_URL = "redis://redis:6379/0"


class AlwaysFailProvider:
    """Fail deterministically at the active model-provider boundary."""

    async def summarize(self, request: ModelRequest) -> ModelSummary:
        """Raise the fixed integration failure."""
        raise TimeoutError("integration provider failure")


async def verify() -> None:
    """Verify initialization, durable identity, and pending-message recovery."""
    identity = uuid4().hex
    exception_id = f"verify-{identity}"
    stream = f"coldline.verify.{identity}"
    group = "verify-workers"
    now = datetime.now(UTC)
    reading = SensorReading(
        reading_id=f"reading-{identity}",
        shipment_id="shipment-integration",
        temperature_c=9.2,
        allowed_min_c=2.0,
        allowed_max_c=8.0,
        recorded_at=now,
    )
    record = ExceptionRecord(
        exception_id=exception_id,
        reading=reading,
        state=ExceptionState.RECEIVED,
        accepted_at=now,
        updated_at=now,
    )
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis = Redis.from_url(REDIS_URL)
    try:
        assert await pool.fetchval("SELECT to_regclass('public.exceptions')") == "exceptions"
        groups = await redis.xinfo_groups("coldline.exception.jobs")
        assert any(
            _text(info[b"name"] if b"name" in info else info["name"]) == "coldline-workers"
            for info in groups
        )

        repository = PostgresExceptionRepository(pool)
        created = await repository.create(record)
        duplicate = await repository.create(record)
        assert created == duplicate
        queued = await repository.transition(
            exception_id, {ExceptionState.RECEIVED}, ExceptionState.QUEUED
        )
        assert queued.state is ExceptionState.QUEUED

        publisher = RedisJobQueue(redis, stream=stream, group=group, consumer="verify-consumer-a")
        await publisher.initialize()
        job = ExceptionJob(exception_id=exception_id, reading=reading, accepted_at=now)
        await publisher.publish(job)
        delivery = await publisher.read(block_ms=100)
        assert delivery is not None and delivery.job == job
        assert await publisher.pending_count() == 1

        recovery = RedisJobQueue(redis, stream=stream, group=group, consumer="verify-consumer-b")
        claimed = await recovery.claim_stale(minimum_idle_ms=0)
        assert claimed is not None and claimed.message_id == delivery.message_id
        assert claimed.delivery_count >= 2
        await recovery.acknowledge(claimed.message_id)
        assert await recovery.pending_count() == 0

        terminal = await WorkerApplication(
            repository,
            AlwaysFailProvider(),
            clock=lambda: now,
            maximum_attempts=3,
        ).process(job, delivery_count=3)
        failed = await repository.get(exception_id)
        assert terminal is ProcessingDisposition.ACK
        assert failed is not None and failed.state is ExceptionState.FAILED
        assert failed.failure_reason == "model_provider_exhausted"
    finally:
        await redis.delete(stream)
        await redis.aclose()
        await pool.execute("DELETE FROM exceptions WHERE exception_id = $1", exception_id)
        await pool.close()
    print(
        "Integration verification passed: PostgreSQL, Redis recovery, and terminal failure "
        "contracts are valid."
    )


def _text(value: str | bytes) -> str:
    """Normalize one Redis response value."""
    return value.decode("utf-8") if isinstance(value, bytes) else value


if __name__ == "__main__":
    asyncio.run(verify())
