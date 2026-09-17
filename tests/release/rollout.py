"""Coldline.

===================

File:              tests/release/rollout.py
Component:         Release tools — Rollout
Purpose:           Build the supplied releases, roll the stack between them, record the result.
Interacts With:    infra/release/manifest.yaml, compose.yaml, Docker, Docker Compose, the API
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Immutable tags, health-gated rollout, rollback, evidence
Tools:             Python 3.12, Docker, Docker Compose, httpx

The tool is supplied and protected. It does exactly what you would type by hand, and
it prints the record you would otherwise have to assemble: which release was asked
for, how long Compose waited, what the first request after the wait saw, and which
build answered. Two things it deliberately does not do: it never builds during a
rollout (`--no-build`), and it never edits `compose.yaml` for you.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import yaml

from tests.runtime_config import host_port

TASK_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = TASK_ROOT / "infra/release/manifest.yaml"
COMPOSE_PROFILES = ("--profile", "observability", "--profile", "localstack")
FIRST_PARTY_SERVICES = ("api", "worker")
TAG_VARIABLE = "COLDLINE_RELEASE_TAG"
Release = Literal["known_good", "candidate"]


class ReleaseError(RuntimeError):
    """Report one actionable rollout failure without a stack trace."""


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Return the supplied release manifest as one mapping."""
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or "releases" not in manifest or "images" not in manifest:
        raise ReleaseError("infra/release/manifest.yaml does not declare images and releases")
    return cast(dict[str, Any], manifest)


def release_tag(release: Release, manifest: dict[str, Any] | None = None) -> str:
    """Return the immutable tag one named release uses."""
    manifest = load_manifest() if manifest is None else manifest
    return str(manifest["releases"][release]["tag"])


def build(manifest: dict[str, Any] | None = None) -> list[str]:
    """Build every manifest release for both first-party images; return the tags built."""
    manifest = load_manifest() if manifest is None else manifest
    built: list[str] = []
    for name, dockerfile in (
        ("api", "infra/containers/api.Dockerfile"),
        ("worker", "infra/containers/worker.Dockerfile"),
    ):
        image = str(manifest["images"][name])
        for release in manifest["releases"].values():
            reference = f"{image}:{release['tag']}"
            arguments = [
                "docker",
                "build",
                "--file",
                dockerfile,
                "--tag",
                reference,
                "--build-arg",
                f"COLDLINE_BUILD_VERSION={release['build_version']}",
            ]
            if name == "api":
                arguments += [
                    "--build-arg",
                    f"COLDLINE_READY_DELAY_SECONDS={release['ready_delay_seconds']}",
                ]
            arguments.append(".")
            subprocess.run(arguments, cwd=TASK_ROOT, check=True)
            built.append(reference)
    return built


def compose_config() -> dict[str, Any]:
    """Return the rendered Compose configuration for the current environment."""
    result = subprocess.run(
        ["docker", "compose", *COMPOSE_PROFILES, "config", "--format", "json"],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(f"docker compose config failed: {result.stderr.strip()}")
    return cast(dict[str, Any], json.loads(result.stdout))


def require_pinned_images(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Refuse to roll a stack whose first-party services still build anonymously."""
    for service in ("initializer", *FIRST_PARTY_SERVICES):
        image = config["services"].get(service, {}).get("image")
        if not isinstance(image, str) or ":" not in image:
            raise ReleaseError(
                f"service {service} has no `image:` name with a tag; "
                "pin it to a manifest release first"
            )
        repository = image.rsplit(":", maxsplit=1)[0]
        expected = manifest["images"]["api" if service == "initializer" else service]
        if repository != expected:
            raise ReleaseError(f"service {service} names image {repository}, expected {expected}")


def compose_records() -> list[dict[str, Any]]:
    """Return the running Compose service records."""
    result = subprocess.run(
        ["docker", "compose", *COMPOSE_PROFILES, "ps", "--all", "--format", "json"],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(f"docker compose ps failed: {result.stderr.strip()}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def container_limits(service: str) -> dict[str, Any]:
    """Return the memory and CPU limits Docker applied to one running service."""
    record = next((entry for entry in compose_records() if entry.get("Service") == service), None)
    if record is None:
        raise ReleaseError(f"service {service} has no container")
    inspected = subprocess.run(
        ["docker", "inspect", str(record["Name"])],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspected.returncode != 0:
        raise ReleaseError(f"docker inspect failed for {service}: {inspected.stderr.strip()}")
    details = json.loads(inspected.stdout)
    host_config = details[0].get("HostConfig", {}) if details else {}
    return {
        "service": service,
        "container": record["Name"],
        "image": record.get("Image"),
        "memory_bytes": int(host_config.get("Memory") or 0),
        "nano_cpus": int(host_config.get("NanoCpus") or 0),
    }


def _api_client() -> httpx.Client:
    port = host_port("COLDLINE_API_HOST_PORT", 8000)
    return httpx.Client(base_url=f"http://localhost:{port}", timeout=5.0)


def probe() -> dict[str, Any]:
    """Return what one request sees right now: readiness status and the build that answered."""
    with _api_client() as client:
        try:
            ready = client.get("/health/ready")
            ready_status: int | None = ready.status_code
        except httpx.HTTPError:
            ready_status = None
        try:
            version = client.get("/version")
            reported = version.json().get("build_version") if version.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            reported = None
    return {"ready_status": ready_status, "build_version": reported}


def wait_until_ready(timeout_seconds: float = 120.0) -> float:
    """Poll readiness until it answers 200; return the seconds that took."""
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        if probe()["ready_status"] == 200:
            return round(time.monotonic() - started, 1)
        time.sleep(1.0)
    raise ReleaseError("the API did not become ready within the timeout")


def roll(release: Release, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move the first-party services to one manifest release and record the transition."""
    manifest = load_manifest() if manifest is None else manifest
    tag = release_tag(release, manifest)
    environment = os.environ.copy()
    environment[TAG_VARIABLE] = tag
    result = subprocess.run(
        ["docker", "compose", *COMPOSE_PROFILES, "config", "--format", "json"],
        cwd=TASK_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(f"docker compose config failed: {result.stderr.strip()}")
    require_pinned_images(json.loads(result.stdout), manifest)
    started = time.monotonic()
    up = subprocess.run(
        [
            "docker",
            "compose",
            *COMPOSE_PROFILES,
            "up",
            "--detach",
            "--no-build",
            "--wait",
            *FIRST_PARTY_SERVICES,
        ],
        cwd=TASK_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    waited = round(time.monotonic() - started, 1)
    if up.returncode != 0:
        detail = up.stderr.strip().splitlines()[-1] if up.stderr.strip() else "no detail"
        raise ReleaseError(
            f"docker compose up --no-build --wait failed for release {release} ({tag}): {detail}"
        )
    first = probe()
    images = {
        entry["Service"]: entry.get("Image")
        for entry in compose_records()
        if entry.get("Service") in FIRST_PARTY_SERVICES
    }
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "release": release,
        "requested_tag": tag,
        "compose_wait_seconds": waited,
        "first_probe": first,
        "running_images": images,
    }


def status() -> dict[str, Any]:
    """Report the running first-party images, the answering build, and applied limits."""
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "probe": probe(),
        "running_images": {
            entry["Service"]: entry.get("Image")
            for entry in compose_records()
            if entry.get("Service") in FIRST_PARTY_SERVICES
        },
        "limits": [container_limits(service) for service in FIRST_PARTY_SERVICES],
    }


def main(argv: list[str] | None = None) -> int:
    """Run one release action from the command line and print its JSON record."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="build every manifest release for both images")
    roll_parser = commands.add_parser("roll", help="move api and worker to one release")
    roll_parser.add_argument("--to", choices=("known_good", "candidate"), required=True)
    commands.add_parser("status", help="print the running images, build, and limits")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            record: dict[str, Any] = {"built": build()}
        elif args.command == "roll":
            record = roll(cast(Release, args.to))
        else:
            record = status()
    except ReleaseError as exc:
        print(f"release action failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
