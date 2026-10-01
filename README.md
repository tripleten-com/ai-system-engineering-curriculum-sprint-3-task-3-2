# Coldline Task 3.2 — Provider reliability

This checkpoint is the verified Task 3.1 release platform with one addition: a supplied,
conformance-tested wrapper that bounds a model-provider call's timeout, attempt count, and
failure classification. The worker does not use it yet, and it does not yet tell a terminal
failure apart from one that might still succeed on a later attempt. Wiring it in, and reacting
correctly to what it raises, is this Task's work.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/tripleten-com/ai-system-engineering-curriculum-sprint-3-task-3-2/tree/main)

## Start the system

Prerequisites are Python 3.12 and Docker with Compose v2. The supplied bootstrap supports macOS
arm64/x86-64, Windows x86-64, and Linux x86-64/aarch64, and installs pinned uv 0.11.8 under
`.tools/bin`. If your computer cannot run the stack locally, use the Codespaces button above.

On macOS and most Linux distributions the interpreter is `python3`; substitute it wherever these
commands say `python`.

```shell
python infra/scripts/bootstrap.py
./.tools/bin/uv sync --frozen
./.tools/bin/uv run --frozen poe preflight
./.tools/bin/uv run --frozen poe start
./.tools/bin/uv run --frozen poe ready
```

PowerShell and POSIX wrappers are available under `infra/scripts/`. After uv is on `PATH`, the
shorter `uv run --frozen poe <task>` form works.

| Service | Local URL | Purpose |
|---|---|---|
| API | `http://localhost:8000` | Submit exception workflows and retrieval queries; `/version` names the build that answers |
| Grafana | `http://localhost:3000` | Use the focused diagnostics dashboard |
| Prometheus | `http://localhost:9090` | Query bounded metrics |
| Jaeger | `http://localhost:16686` | Inspect local traces |
| LocalStack S3 | `http://localhost:4566` | Inspect the emulated object-storage endpoint |

Each of these ports can be overridden by setting the matching `COLDLINE_API_HOST_PORT`,
`COLDLINE_GRAFANA_HOST_PORT`, `COLDLINE_PROMETHEUS_HOST_PORT`, `COLDLINE_JAEGER_HOST_PORT`, or
`COLDLINE_LOCALSTACK_HOST_PORT` environment variable in your shell environment or a local `.env`
file (copy `.env.example`) if a default collides with something already running on your machine.
Keep the override in place for every `poe` command.

This Task runs as its own Compose project, `coldline-task-3-2`. If an earlier Task's stack is
still running, run `poe stop` in that Task's repository first; otherwise `poe start` here fails
because the published ports are already taken.

PostgreSQL, Redis, worker metrics, and OTLP remain inside the Compose network. Codespaces uses the
same `compose.yaml` and keeps every forwarded port private.

## Command path

For this Task, run the supplied commands in this order:

```text
poe unit
poe contract
poe verify
```

| Command | Use |
|---|---|
| `poe unit` | Run fast isolated behavior tests, including the resilient-provider wrapper's own tests and the worker's use-case and wiring tests |
| `poe contract` | Check interfaces, boundaries, submissions, and repository structure |
| `poe smoke` | Check the initialized running platform |
| `poe e2e` | Run the external API-to-worker workflow |
| `poe verify` | Run the public student verification path |
| `poe student-tests` | Run the supplied tests under `tests/student/`; this Task permits no additions there |
| `poe restart` | Restart the existing API and worker containers **without rebuilding** |
| `poe stop` | Remove containers and the network, keeping named volumes |
| `poe reset` | Remove containers, the network, and local named volumes |

For Task 3.2, `poe verify` runs the unit suite — including the three tests your wiring must
satisfy — then rebuilds and starts the stack, ingests the supplied corpus, and runs the smoke
tests, the end-to-end exception workflow, and the answer-sheet checks.

## Folder map

```text
repository root/
├── docs/                Student guidance, public contracts, and fidelity notes
│   ├── contracts/       Machine-readable public contracts
│   ├── fidelity/        Local-runtime boundary notes
│   ├── architecture/    Supplied vector engine technical profiles, in prose
│   ├── retrieval/       Supplied retrieval pipeline reference
│   └── student/         This Task's contract
├── config/              Retrieval configuration, settled and supplied from Sprint 2
├── infra/               Local setup and runtime configuration
│   ├── containers/      The API and worker Dockerfiles, with the build identity arguments
│   ├── release/         The supplied Task 3.1 release manifest, unchanged
│   ├── corpus/          Supplied synthetic corpus, query set, and designated investigation
│   ├── judge/           Supplied cached judge evidence and its provenance record
│   ├── profiles/        Supplied engine and emulator profiles, and their provenance record
│   └── postgres/        Database initialization and the migration baseline stamp
├── loadtest/            Supplied traffic profile and provider-latency harness
├── migrations/          Alembic environment, revision template, and revisions
├── src/
│   ├── api/             HTTP application code, the retrieval and document paths, composition
│   ├── worker/          Background application code — your two files live here
│   ├── domain/          Shared domain code, contracts, the failure taxonomy, service and repository contracts
│   ├── ports/           Application interfaces
│   └── adapters/        Technology-specific implementations, including the supplied resilient model-provider wrapper
└── tests/
    ├── unit/            Isolated behavior checks
    ├── benchmark/       Supplied evaluation harness, metrics, and adoption policy
    ├── contract/        Interface, retrieval, and repository checks
    ├── diagnostics/     Supplied stage inspector
    ├── doubles/         Supplied deterministic test doubles
    ├── student/         Supplied student tests; no additions in this Task
    ├── smoke/           Running-platform checks
    └── e2e/             Supplied workflow tools and checks
```

## Overview

Use the Task 2 lesson (Task 3.2 in this repository) to decide what to do. This README covers
local setup and repository orientation.

1. `README.md` — local setup, commands, and permitted changes.
2. [`docs/student/task-3-2-contract.md`](docs/student/task-3-2-contract.md) — the two steps,
   what each check verifies, and the permitted paths.
3. `src/adapters/model/resilient.py` — the supplied wrapper you wire in; read its docstrings.
4. `src/domain/errors.py` — the failure taxonomy `resilient.py` raises.
5. `src/worker/config.py` — the three settings you read: `model_timeout_ms`,
   `model_provider_max_attempts`, `model_retry_backoff_ms`.

The application source lives in five flat packages:

| Package | Responsibility |
|---|---|
| `api` | HTTP delivery, API use cases, the retrieval workflow, versioned routes, configuration, and composition |
| `worker` | Background processing, retries, configuration, and composition |
| `domain` | Provider-neutral contracts, state rules, identity, redaction, embedding, chunking, fusion, access constraints, failure classification, service and repository contracts |
| `ports` | Exactly five visible application interfaces |
| `adapters` | PostgreSQL, pgvector retrieval, Redis Streams, S3-compatible object storage, deterministic model, the resilient model-provider wrapper, logs, traces |

`src/api/bootstrap.py` and `src/worker/bootstrap.py` compose each process from its settings and
adapters. Process settings live in `src/api/config.py` and `src/worker/config.py`.

## The five ports

Find the available interfaces in `src/ports/`. A port describes an application capability; an
adapter provides it using a concrete technology.

| Port | General responsibility |
|---|---|
| `ModelProvider` | Call an AI model service |
| `Retriever` | Look up relevant context or documents |
| `ObjectStore` | Store large binary objects or files |
| `JobQueue` | Publish and consume background work |
| `SecretProvider` | Read API keys and credentials |

Redis Streams still carries `JobQueue` in this Task. Task 3.3 introduces the supplied LocalStack
SQS and dead-letter binding.

## Test levels

| Level | Requires Compose | Main question |
|---|---:|---|
| Unit | No | Does one responsibility behave correctly, including failures? |
| Contract | Some | Do interfaces, schemas, paths, and dependency rules stay compatible? |
| Smoke | Yes | Did the complete local platform initialize and become observable? |
| E2E | Yes | Can an external client complete the supplied workflow? |

Contract checks marked `runtime` need the running stack. `poe contract` skips them; `poe verify`
and `poe runtime-contract` run them.

## Submission checks

Run `poe verify` locally before opening your student pull request. Public GitHub CI repeats
the student checks. This Task records `answers: {}`: your implementation and its tests are the
evidence, so there is no separate protected answer check. Follow the Task lesson's
instructor-review and progression policy.

## Task boundary

Task 3.2 asks you to wrap the supplied deterministic model provider in the supplied
`ResilientModelProvider`, using the three settings already defined in `src/worker/config.py`, and
to make the worker record a terminal provider failure on the very first delivery instead of
retrying it like any other failure.

These paths are student-editable:

- `src/worker/bootstrap.py`
- `src/worker/use_cases.py`
- `submission.yaml`

Keep the resilient wrapper, the failure taxonomy, the provider settings, and every test file
exactly as supplied; the public checks compare them. Everything else in this repository is
supplied, including `compose.yaml` (Task 1's already-verified release configuration), the
release manifest, and the rest of the application source.

### Student walkthrough

See **Task 2: Provider reliability** in your course platform for the full walkthrough. In
outline: read `resilient.py`'s docstrings and its own tests, wrap the deterministic provider with
it in `build_model_provider` in `bootstrap.py` using the three supplied settings, add the missing
`except TerminalProviderError` branch in `use_cases.py` ahead of the existing catch-all, run
`poe unit` until the three assessed tests pass without breaking the existing ones, run
`poe verify`, and open your pull request.

## Operational limits

This local system does not authenticate users, terminate TLS, or manage production secrets.
The Compose PostgreSQL password and the LocalStack access keys are local-only non-secret
credentials. Never place real credentials, personal data, or production records in this
repository.

The resilient wrapper's timeout and retry bounds are a local reliability primitive, not a
capacity, latency-SLO, or availability claim: the deterministic provider it wraps has no network
to fail, so a real hosted provider's throttling, partial-network, or cost behavior is still
unproven here.

Named volumes preserve local PostgreSQL, Redis, Prometheus, Grafana, and Jaeger state across
`poe stop`. LocalStack object contents are deliberately not persisted; the initializer re-uploads
the supplied corpus artifacts on every start. The `poe reset` command deletes the named volumes.
This topology makes no backup, replication, high-availability, disaster-recovery, capacity,
latency-SLO, or availability claim.

See [JobQueue fidelity](docs/fidelity/JobQueue.md),
[ModelProvider fidelity](docs/fidelity/ModelProvider.md),
[ObjectStore fidelity](docs/fidelity/ObjectStore.md), and
[Retriever fidelity](docs/fidelity/Retriever.md) for the active adapter boundaries. The
[local runtime evidence](docs/fidelity/local-runtime.md) records the current measurement and its
qualification limits.
