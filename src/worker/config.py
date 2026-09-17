"""Coldline.

===================

File:              src/worker/config.py
Component:         Worker — Config
Purpose:           Own and validate every worker environment read.
Interacts With:    Redis Streams, domain, ports, and adapters
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Background processing, retries, idempotency, bounded resilience
Tools:             Python 3.12, Redis, Pydantic
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Describe the protected runtime configuration for the worker service."""

    model_config = SettingsConfigDict(env_prefix="COLDLINE_", extra="forbid")

    database_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)
    otel_endpoint: str = Field(min_length=1)
    service_name: str = "coldline-worker"
    stream_name: str = "coldline.exception.jobs"
    consumer_group: str = "coldline-workers"
    consumer_name: str = "worker-1"
    maximum_attempts: int = Field(default=3, ge=1, le=3)
    stale_message_ms: int = Field(default=30_000, ge=1_000)
    model_latency_ms: int = Field(default=250, ge=0, le=10_000)
    metrics_port: int = Field(default=9100, ge=1024, le=65535)
    # Task 3.1 release identity, baked into the image by the release manifest's build
    # argument and logged once at startup so a rollout is visible in the worker logs.
    build_version: str = Field(default="dev", min_length=1, max_length=64)
    # Task 3.2 provider-resilience bounds. These wrap every ModelProvider call
    # in its own timeout and attempt budget, independent of the transport's
    # own delivery-count-based redelivery above.
    model_timeout_ms: int = Field(default=2_000, ge=1, le=30_000)
    model_provider_max_attempts: int = Field(default=2, ge=1, le=5)
    model_retry_backoff_ms: int = Field(default=100, ge=0, le=10_000)
