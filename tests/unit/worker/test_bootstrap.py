"""Coldline.

===================

File:              tests/unit/worker/test_bootstrap.py
Component:         Unit tests — Test Bootstrap
Purpose:           Unit tests for the worker's model provider composition.
Interacts With:    One isolated source responsibility
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fast feedback, bounded resilience, composition wiring
Tools:             Python 3.12, pytest
"""

from types import SimpleNamespace

import pytest

from adapters.model import DeterministicModelProvider, ResilientModelProvider
from worker.bootstrap import build_model_provider


@pytest.mark.assessed
def test_worker_composes_the_resilient_provider_from_settings() -> None:
    """The worker's provider is the supplied wrapper, bounded by the three settings in seconds."""
    settings = SimpleNamespace(
        model_latency_ms=5,
        model_timeout_ms=2500,
        model_provider_max_attempts=3,
        model_retry_backoff_ms=200,
    )
    provider = build_model_provider(settings)  # type: ignore[arg-type]
    assert isinstance(provider, ResilientModelProvider), "wrap the deterministic provider"
    assert isinstance(provider._inner, DeterministicModelProvider)
    assert provider._timeout_seconds == pytest.approx(2.5), "model_timeout_ms is milliseconds"
    assert provider._max_attempts == 3
    assert provider._backoff_seconds == pytest.approx(0.2), "model_retry_backoff_ms is milliseconds"
