# AutoHeal Studio v2 — package reference

The Python standard-library backend and browser workbench implement the **Self-Correction “Code Execution & Auto-Heal” Loop** for the joint Generative AI Laboratory submission by **Aayush Kumar Tiwari — 16014223003, LY AI & DS B2** and **Prateeksha Kini — 16014223061, LY AI & DS B3**, academic year **2026–27**.

[Repository](https://github.com/aayushtiwari845/AutoHeal) · [Project overview and Windows launch](../README.md) · [Report PDF](../docs/report/AutoHeal_Project_Report.pdf) · [Report Word](../docs/report/AutoHeal_Project_Report.docx) · [Workbench screenshot](../docs/screenshots/01-workbench-overview.png)

## Components

| Path | Responsibility |
| --- | --- |
| `server.py` | Loopback HTTP service, host/origin checks, static assets, snapshots, stage advance, cancellation, and trace export |
| `engine.py` | Bounded generate/execute/evaluate/reflect state machine, automatic or manual gates, feedback, and stopping rules |
| `provider.py` | Streaming Ollama and optional compatible API transports, local environment configuration, response bounds, and provider-error handling |
| `executor.py` | Source-policy checks, child-only Python execution, output capture, real line observations, timeout, cancellation, and resource controls |
| `presets.py` | Fixed datasets, labelled initial samples, task rules, independent semantic references, and structural checks for custom tasks |
| `web/` | Dependency-free Windows 95 inspired workbench, source/changes, captured-line replay, terminals, checks, and stage controller |
| `tests/` | Independent reference calculations, executor contracts, state transitions, provider behavior, manual gates, trace precision, and HTTP protections |

The application binds only to `127.0.0.1:8765`, retains at most 40 runs in memory, and permits at most two active workers. A run allows one to five attempts, with a one-to-five-second timeout for each subprocess. Generation has a separate bounded provider deadline; manual inspection time is not subprocess execution time.

## Observable execution

Automatic mode advances until validation passes or the attempt limit is reached. Manual mode pauses **before Generate, Execute, Evaluate, and Reflect**. Advancing Generate on a repair attempt produces the replacement source; a successful Evaluate stops immediately without an unnecessary reflection or repair.

Snapshots contain the task and `input_data`, provider/mode, control mode, attempts, stage history, raw provider response progress, error feedback, result checks, and final outcome. Each attempt records source, a concise technical diagnosis, actual stdout/stderr, return code, execution duration, error type/line, validation, and captured `exec_steps` when tracing is enabled.

Line records are actual CPython events for generated source. They include the source line, event type, and bounded local variables; a `line` event is recorded **before the statement executes**. Exception events include caught exceptions, so the final attempt status must be read from execution and validation outcomes. Replay of these observations is distinct from the server's manual stage gates and is not an interactive Python debugger. Trace caps and truncation are disclosed in the attempt.

The optional seeded first candidate is prewritten and labelled. **Live Ollama/API modes** generate ordinary candidates and repairs. **Scripted replay** makes no model calls: it executes predetermined faulty and repaired programs through the same executor and validator. A custom task accepts optional finite JSON `data` of at most 12,000 serialized characters, provided as `DATA`; its non-empty JSON-object check is structural only. Fixed presets receive independent semantic checks, and a successful process exit alone does not establish correctness.

## HTTP API

| Method and route | Purpose |
| --- | --- |
| `GET /api/status` | Service identity `autoheal-studio`, version `2.x`, providers/models, control modes, limits, and trace semantics; no credentials |
| `GET /api/presets` | Verified task contracts, datasets, expected fields/reference, and explicitly prewritten `seed_preview` |
| `POST /api/runs` | Start an asynchronous live or replay run |
| `GET /api/runs/{id}` | Read the current snapshot, including waiting stage and captured output |
| `POST /api/runs/{id}/advance` | Release the current manual gate using its `step_token` |
| `POST /api/runs/{id}/cancel` | Cancel a waiting stage, model request, or child execution |
| `GET /api/runs/{id}/export` | Download the selected run as JSON |

Creation accepts `preset_id`, `task`, optional custom `data`, `mode` (`live`/`replay`), `provider` (`ollama`/`api`), `model`, `control_mode` (`auto`/`manual`), `max_attempts`, `timeout`, `seed_failure`, and `trace_execution`. Presets retain their fixed contract and data.

Manual snapshots expose `awaiting_step`, `next_phase`, `next_attempt`, and `step_token`. Send the exact current token in the advance request. Repeating an already consumed token is idempotent; an unrelated stale token returns a conflict. Cancellation wakes a waiting gate. Mutations require JSON and an accepted local host/origin; wildcard cross-origin access is not enabled.

## Provider configuration and privacy

The default local model is `qwen2.5-coder:7b` via Ollama at `127.0.0.1:11434`. Optional API configuration is documented in [`.env.example`](../.env.example): `AUTOHEAL_API_BASE`, `AUTOHEAL_API_MODEL`, and `AUTOHEAL_API_KEY`, with `GROQ_API_KEY` as an alternative key variable. Only the documented settings are loaded from `.env`, and existing environment values win. Restart the server to load file changes.

API mode requires an explicitly selected remote provider and sends task data, source, and relevant feedback externally. Ollama mode keeps this traffic local; scripted replay has no provider traffic. Browser users never enter keys. Credentials remain in the server environment, are excluded from snapshots and exports, and do not enter the child environment. `.env` is excluded from Git. Run exports still contain task data and generated content, so inspect them before sharing.

## Execution limits

Source-policy checks, restricted imports/builtins, a child audit hook, `python -I -S`, a disposable directory, no stdin, a restricted environment, output caps, recorded-trace caps, and process timeouts provide layered execution constraints. File, network, process, private-attribute, and introspection access are disallowed by application controls. Invalid JSON, duplicate keys, non-finite values, runtime errors, policy failures, timeouts, and semantic mismatches remain explicit failures.

Windows Job Object limits are best effort: 384 MB process memory, one process, and kill-on-close behavior, with `job_limit_active` recorded per attempt. Cancellation terminates a child or closes provider transport; a remote provider or Ollama may briefly continue internal work after the connection closes. Cancelled workers retain their capacity until cleanup finishes.

These controls are **not a hardened OS security sandbox**. The workbench is intended for trusted local laboratory demonstrations, with no claim that application-level restrictions safely isolate hostile code.

## Checks and launch

From the repository root:

```powershell
& ".\Launch AutoHeal.cmd"
python tools/run_checks.py
node --check autoheal/web/app.js
```

The backend checks use the standard library and mocked providers. Node is only needed for the optional JavaScript syntax check. The application requires no Python package installation or browser build step. The report and current verification logs contain the recorded test outcomes.
