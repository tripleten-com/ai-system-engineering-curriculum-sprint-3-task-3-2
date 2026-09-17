"""Coldline.

===================

File:              tests/contract/test_runtime_adapters.py
Component:         Contract tests — Runtime adapters
Purpose:           Runs real PostgreSQL and Redis contracts inside the worker container.
Interacts With:    Docker Compose, PostgreSQL, Redis, and worker image
Sprint/Task:       Sprint 1 — Project 1
Concepts:          Initialization, idempotency, pending recovery, terminal failure
Tools:             Python 3.12, pytest, Docker Compose
"""

import subprocess
from pathlib import Path

import pytest

TASK_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.runtime


def test_postgres_and_redis_adapters_preserve_runtime_contracts() -> None:
    """Catch a provider adapter that passes unit tests but fails on real services."""
    verifier = (TASK_ROOT / "tests" / "contract" / "runtime_adapters.py").read_text(
        encoding="utf-8"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "worker",
            "python",
            "-",
        ],
        cwd=TASK_ROOT,
        input=verifier,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Integration verification passed" in result.stdout
