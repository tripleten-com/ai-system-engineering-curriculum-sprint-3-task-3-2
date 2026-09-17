"""Coldline.

===================

File:              tests/contract/test_release.py
Component:         Contract tests — Release
Purpose:           Check pinned images, the readiness gate, resource bounds, rollout and rollback.
Interacts With:    compose.yaml, infra/release/manifest.yaml, the running stack, submission.yaml
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Immutable tags, health-gated rollout, rollback, bounded resources
Tools:             Python 3.12, pytest, Docker Compose

Every check here reads the delivered Compose file and the running stack. None of them
reads the evidence pack: the pack is an interpretation exercise, and these are the
behavior your repository has to show on its own.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from tests.release import rollout
from tests.runtime_config import host_port

TASK_ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 * 1024
pytestmark = [pytest.mark.runtime, pytest.mark.assessed]


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    """Load the supplied release manifest once."""
    return rollout.load_manifest()


@pytest.fixture(scope="module")
def answers() -> dict[str, Any]:
    """Load the recorded answers once; a blank sheet still lets the runtime checks run."""
    document = yaml.safe_load((TASK_ROOT / "submission.yaml").read_text(encoding="utf-8"))
    recorded = document.get("answers") if isinstance(document, dict) else None
    return recorded if isinstance(recorded, dict) else {}


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    """Render the delivered Compose file with no release tag override."""
    return rollout.compose_config()


def _duration_seconds(value: object) -> float:
    """Parse a Compose duration such as `25s`, `1m30s`, or nanoseconds."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) / 1_000_000_000 if value > 1_000_000 else float(value)
    if not isinstance(value, str):
        return 0.0
    total = 0.0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)(h|m|s|ms)", value):
        total += float(amount) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    return total


def test_first_party_images_are_pinned_to_the_known_good_tag(
    config: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Each first-party service names an immutable image, defaulting to the known-good tag."""
    known_good = str(manifest["releases"]["known_good"]["tag"])
    for service, image_name in (
        ("api", manifest["images"]["api"]),
        ("initializer", manifest["images"]["api"]),
        ("worker", manifest["images"]["worker"]),
    ):
        image = config["services"][service].get("image")
        assert image == f"{image_name}:{known_good}", (
            f"{service} must name {image_name}:{known_good} through COLDLINE_RELEASE_TAG; "
            f"got {image!r}"
        )


def test_api_health_gate_probes_readiness_and_tolerates_the_warm_up(
    config: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """The API health check asks for readiness and gives the candidate its warm-up time."""
    healthcheck = config["services"]["api"].get("healthcheck", {})
    command = " ".join(str(part) for part in healthcheck.get("test", []))
    assert "/health/ready" in command, "the API health check must probe /health/ready"
    assert "/health/live" not in command, "liveness is not a readiness gate"
    warm_up = float(manifest["releases"]["candidate"]["ready_delay_seconds"])
    start_period = _duration_seconds(healthcheck.get("start_period"))
    tolerated = _duration_seconds(healthcheck.get("interval")) * int(healthcheck.get("retries", 0))
    assert start_period >= warm_up or tolerated >= warm_up + 10, (
        "the gate must tolerate the candidate warm-up through start_period or interval x retries"
    )


def test_resource_bounds_are_declared_within_the_published_ranges(
    manifest: dict[str, Any], answers: dict[str, Any]
) -> None:
    """Docker applied a memory and CPU limit to api and worker, inside the manifest bounds."""
    for service in ("api", "worker"):
        bounds = manifest["resource_bounds"][service]
        limits = rollout.container_limits(service)
        memory_mib = limits["memory_bytes"] / MIB
        cpus = limits["nano_cpus"] / 1_000_000_000
        low, high = bounds["memory_mib"]
        assert low <= memory_mib <= high, (
            f"{service} memory limit {memory_mib:.0f} MiB is outside [{low}, {high}]"
        )
        low_cpu, high_cpu = bounds["cpus"]
        assert low_cpu <= cpus <= high_cpu, (
            f"{service} cpu limit {cpus} is outside [{low_cpu}, {high_cpu}]"
        )
        recorded_memory = answers.get(f"{service}_memory_limit_mib")
        recorded_cpus = answers.get(f"{service}_cpu_limit")
        assert recorded_memory == round(memory_mib), (
            f"answers.{service}_memory_limit_mib must record the applied limit {memory_mib:.0f}"
        )
        assert isinstance(recorded_cpus, int | float) and abs(float(recorded_cpus) - cpus) < 0.01, (
            f"answers.{service}_cpu_limit must record the applied limit {cpus}"
        )


def _run_scenario() -> None:
    """Complete one exception through the API and worker; the user-visible path must work."""
    fixture = json.loads(
        (TASK_ROOT / "tests/e2e/baseline-exception.json").read_text(encoding="utf-8")
    )
    reading = dict(fixture["reading"])
    reading["reading_id"] = f"release-check-{int(time.time() * 1000)}"
    port = host_port("COLDLINE_API_HOST_PORT", 8000)
    with httpx.Client(base_url=f"http://localhost:{port}", timeout=5.0) as client:
        accepted = client.post("/api/v1/readings", json=reading)
        assert accepted.status_code == 202, accepted.text
        status_url = accepted.json()["status_url"]
        for _ in range(60):
            record = client.get(status_url).json()
            if record["state"] == "COMPLETED":
                return
            assert record["state"] != "FAILED", "the exception workflow failed after the rollout"
            time.sleep(0.5)
    pytest.fail("the exception workflow did not complete after the rollout")


def test_roll_forward_serves_only_after_the_candidate_is_ready(
    manifest: dict[str, Any], answers: dict[str, Any]
) -> None:
    """Rolling to the candidate returns only when it can serve, and the candidate answers."""
    try:
        record = rollout.roll("candidate", manifest)
    except rollout.ReleaseError as exc:
        pytest.fail(str(exc))
    candidate = str(manifest["releases"]["candidate"]["build_version"])
    assert record["first_probe"]["ready_status"] == 200, (
        f"the first request after the gate saw {record['first_probe']['ready_status']}, not 200"
    )
    assert record["first_probe"]["build_version"] == candidate
    _run_scenario()
    assert answers.get("observed_candidate_version") == candidate


def test_roll_back_restores_the_known_good_build(
    manifest: dict[str, Any], answers: dict[str, Any]
) -> None:
    """Rolling back returns the known-good build and the workflow still completes."""
    try:
        record = rollout.roll("known_good", manifest)
    except rollout.ReleaseError as exc:
        pytest.fail(str(exc))
    known_good = str(manifest["releases"]["known_good"]["build_version"])
    assert record["first_probe"]["ready_status"] == 200
    assert record["first_probe"]["build_version"] == known_good
    _run_scenario()
    assert answers.get("observed_rollback_version") == known_good
    assert answers.get("known_good_tag") == manifest["releases"]["known_good"]["tag"]
    assert answers.get("candidate_tag") == manifest["releases"]["candidate"]["tag"]
