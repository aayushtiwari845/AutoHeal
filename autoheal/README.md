# AutoHeal Studio

A joint Generative AI lab project for **Aayush Kumar Tiwari (16014223003, LY AI & DS B2)** and **Prateeksha Kini (16014223061, LY AI & DS B3)**.

The dashboard exposes a complete **generate → execute → evaluate → reflect → repair** loop. Every candidate, concise technical diagnosis, stdout, stderr, exit code, execution duration, error location, and validation decision appears in an exportable JSON trace. Successful validation stops the loop immediately. Each run allows at most five attempts and each execution at most five seconds.

## Modes and honest claims

- **Live local model:** Ollama generates each ordinary candidate and repair using `qwen2.5-coder:7b`. No hosted API, API key, or paid service is required. Model loading and generation can take longer than code execution; the execution timeout applies to the child Python process only.
- **Controlled first failure:** An optional, explicitly marked broken first candidate demonstrates an exception or semantic error. The local model must generate the repaired candidate. The seeded source is never presented as model-generated code.
- **Scripted replay:** Predetermined broken and repaired programs are really executed and validated. This provides a repeatable offline demonstration of orchestration, diagnostics, and execution. It is not evidence of model intelligence.
- **Custom task:** A live model processes a user task and must output a non-empty JSON object. This checks execution and structure; custom answers have no independent correctness oracle.

## Verified scenarios

| Scenario | Controlled fault | Independent target |
| --- | --- | --- |
| Sales | Summing dirty strings raises `TypeError` | 6 valid rows; 2 rejected; total 520; North 160, South 180, West 180; tie broken alphabetically |
| Text | Calling `lowercase()` raises `AttributeError` | 14 tokens; 7 unique; code 4, ai 3, reliable 3; stable tie ordering |
| Grades | Unweighted means execute but fail semantic validation | Weighted averages 78, 77, 95.6, 50.5; class average 75.28; 3 passing students |

Expected values are specified separately from candidate source and independently recalculated in the test suite. The model receives task rules and data, not the expected-answer object. Zero exit code alone never establishes preset correctness.

## Architecture

| File | Responsibility |
| --- | --- |
| `server.py` | Loopback HTTP server, static dashboard, origin/host checks, run and export endpoints |
| `engine.py` | Asynchronous state machine, bounded attempt history, stop conditions, cancellation, feedback |
| `provider.py` | Local Ollama streaming transport; bounded repair context; concise diagnosis/code response |
| `executor.py` | AST checks, child-only execution, audit guard, isolated temporary workspace, bounded capture |
| `presets.py` | Public scenario definitions, independent expected results, semantic/structural validation |
| `web/` | Minimal browser interface, code inspection, live attempt timeline, trace download |
| `tests/test_core.py` | Independent references, executor limits, state transitions, local HTTP protections |

The HTTP API binds to `127.0.0.1:8765`. A server on another interface is refused. `GET /api/status` identifies the service as `autoheal-studio`; `GET /api/presets` returns the three scenarios; `POST /api/runs` starts an asynchronous run; `GET /api/runs/{id}` returns a snapshot; `POST /api/runs/{id}/cancel` cancels it; `GET /api/runs/{id}/export` downloads its trace. Mutations require JSON and an accepted local host/origin. No wildcard CORS is enabled. Runs are kept only in memory and history is bounded to 40 runs with at most two active runs.

## Execution boundaries

This is a **defense-in-depth constrained subprocess, not a hard OS security sandbox**. It is appropriate for trusted local lab demonstrations. It must not be deployed as a public service or used to execute deliberately hostile programs. For hostile workloads, add an operating-system sandbox or container with separate user privileges, a read-only filesystem, disabled network, and resource controls.

Generated source is parsed before execution, with no execution in the parent. Only a restricted Python subset and approved numeric/text modules are available. File, network, process, introspection, private-attribute, and native-library access are denied through AST/import/builtin restrictions plus a child audit hook. Each program runs under `python -I -S` in a disposable directory with a secret-free environment allowlist and no stdin. Standard output/error are capped, repetitive lines condensed, and provider context trimmed. Invalid JSON, duplicate keys, non-finite JSON values, policy violations, timeouts, runtime errors, and semantic mismatches are explicit failures.

On Windows, a best-effort Job Object adds a **384 MB process memory cap**, one-process limit, and kill-on-close behavior. The trace reports `job_limit_active` for every executed attempt rather than silently assuming the operating-system limit worked. Cancellation stops the dashboard run immediately, kills an executing child, and closes an active provider stream; the local Ollama service may briefly continue internal work while its connection is being closed. A provider failure stops the run without inventing a successful result.

## Verification

`python -m unittest discover -s autoheal/tests -v`

The 33-test suite verifies independent Decimal-based reference results, all three repair paths, exact exception lines, syntax errors, hangs, flooding, denied file/network/process access, JSON-format failures, cancellation races, provider failure, first-success stop, five-attempt exhaustion, semantic failures after a successful process exit, custom-validation limitations, and HTTP host/origin restrictions. It also checks that semantic feedback identifies exact failing field paths while excluding reference answers, numeric overflow cannot enter JSON exports, and cancelled unfinished workers retain their capacity and history slots until cleanup. The Python backend uses only the standard library.
