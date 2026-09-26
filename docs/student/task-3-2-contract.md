# Task 3.2 — Provider reliability contract

Wire the supplied `ResilientModelProvider` around the deterministic model provider, and make
the worker fail fast on a terminal failure instead of spending redeliveries on an outcome that
cannot change. You edit two files. You do not write a new adapter.

## What is assessed, and by whom

| Assessed | By |
|---|---|
| The pull request changes only `src/worker/bootstrap.py`, `src/worker/use_cases.py`, and `submission.yaml` | Automated, in this repository |
| The worker calls the model provider through a bounded timeout and a bounded number of attempts | Automated, against `build_model_provider` in `src/worker/bootstrap.py` |
| A terminal provider failure is recorded on the very first delivery, never waiting for retryable exhaustion | Automated, against `WorkerApplication` |
| A retryable failure keeps today's behavior: it retries across deliveries and only fails once the delivery limit is spent | Automated, against `WorkerApplication` |
| Your reasoning about why a fixed inline retry loop is not the same as a bounded one | Your instructor, at the Project Defense |

## What is already supplied

| Supplied | Where | Note |
|---|---|---|
| The bounded timeout, retry, and classification wrapper | `src/adapters/model/resilient.py` | conformance-tested; do not edit |
| The failure taxonomy it raises | `src/domain/errors.py` | `TerminalProviderError` cannot succeed on a later attempt; `RetryableProviderError` is raised once its own attempts are spent |
| The provider-resilience settings | `src/worker/config.py` | `model_timeout_ms`, `model_provider_max_attempts`, `model_retry_backoff_ms`, each bounded |
| The wrapper's own tests | `tests/unit/adapters/test_resilient_model_provider.py` | prove the wrapper in isolation; you are not graded on them directly |
| The two tests this Task adds to the worker's suite | `tests/unit/worker/test_use_cases.py` | `test_terminal_provider_failure_is_recorded_on_the_first_delivery` and `test_terminal_provider_failure_at_the_final_delivery_is_still_distinct` |
| The wiring test for the worker's provider | `tests/unit/worker/test_bootstrap.py` | `test_worker_composes_the_resilient_provider_from_settings` |

## The two steps

### Step 1 — Wire the resilient provider into the worker

`src/worker/bootstrap.py` builds the worker's model provider in `build_model_provider(settings)`,
and `run` passes whatever it returns to `WorkerApplication`. It currently returns a bare
`DeterministicModelProvider(latency_ms=settings.model_latency_ms)`. Nothing bounds how long that
call may run, and nothing bounds how many times it is retried before the worker gives up on it.

Change `build_model_provider` to wrap it in `ResilientModelProvider`, reading the three settings
`src/worker/config.py` already supplies: `model_timeout_ms`, `model_provider_max_attempts`, and
`model_retry_backoff_ms` (each is milliseconds; `ResilientModelProvider` takes seconds). Return
the wrapped provider, not the bare deterministic one.

### Step 2 — Fail fast on a terminal failure

`src/worker/use_cases.py`'s `WorkerApplication.process` currently catches every provider
exception the same way: `except Exception:` retries until `delivery_count` reaches
`maximum_attempts`, then records `failure_reason="model_provider_exhausted"`. That is correct for
a failure that might clear on a later attempt, but it is the wrong response to a failure the
provider has already classified as terminal — retrying it wastes two redeliveries on an outcome
that was never going to change.

Add an `except TerminalProviderError:` branch, ahead of the existing `except Exception:` branch,
that transitions the record straight to `FAILED` with `failure_reason="model_provider_terminal_failure"`
and returns `ACK`, regardless of `delivery_count`. Import `TerminalProviderError` from
`domain.errors`. Leave the existing `except Exception:` branch exactly as it is: a
`RetryableProviderError` from the wrapper, or any other unclassified failure, still retries until
exhausted.

## Commands

```shell
poe unit          # includes the wrapper's own tests and the worker's use-case and wiring tests
poe contract      # structure, submission, and boundary checks
poe verify        # the full public student verification path
```

## What the checks verify

| Check | What it looks at |
|---|---|
| `test_worker_composes_the_resilient_provider_from_settings` | `build_model_provider` must return a `ResilientModelProvider` around the deterministic provider, with the timeout, attempt, and backoff settings converted from milliseconds to seconds |
| `test_terminal_provider_failure_is_recorded_on_the_first_delivery` | A terminal failure on `delivery_count=1` must return `ACK`, transition to `FAILED`, and record `model_provider_terminal_failure` |
| `test_terminal_provider_failure_at_the_final_delivery_is_still_distinct` | The same terminal outcome at `delivery_count=3` must still record `model_provider_terminal_failure`, not `model_provider_exhausted` |
| `test_third_provider_failure_is_recorded_and_acknowledged` and its neighbors | The existing retryable-until-exhausted behavior must still hold, unchanged, for anything that is not a `TerminalProviderError` |
| `test_resilient_model_provider.py` (supplied, unmodified) | The wrapper itself: a hanging call is bounded by its own timeout; a retryable failure may still succeed; attempts stop at the configured bound; a terminal failure is never retried |

## Student-editable paths

- `src/worker/bootstrap.py`
- `src/worker/use_cases.py`
- `submission.yaml`

Keep `src/adapters/model/resilient.py`, `src/domain/errors.py`, `src/worker/config.py`, and every
test file exactly as supplied. The resilience wrapper is a conformance-tested adapter, not this
Task's assignment; wiring it in correctly, and reacting correctly to what it raises, is.
