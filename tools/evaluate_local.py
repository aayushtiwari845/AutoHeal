"""Record small, reproducible live-model evaluations against the running server."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"succeeded", "exhausted", "provider_error", "cancelled"}


def request(url, payload=None):
    raw = json.dumps(payload).encode() if payload is not None else None
    with urlopen(Request(url, data=raw, headers={"Content-Type": "application/json"}), timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--output", default="docs/evidence/live-summary.json")
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    traces = output.parent / "live-traces"
    traces.mkdir(exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    summary = {"source_commit": revision, "scope": "Six cases: three fixed datasets, each with and without a labelled controlled first fault. Small descriptive evaluation; not a general model benchmark.", "api_live_tested": False, "runs": []}
    for seeded in (True, False):
        for preset in ("sales", "grades", "text"):
            label = f"{preset}-{'seeded' if seeded else 'unseeded'}"
            config = {"preset_id": preset, "mode": "live", "provider": "ollama", "model": args.model, "control_mode": "auto", "trace_execution": True, "seed_failure": seeded, "max_attempts": 5, "timeout": 5}
            run_id = request(args.base + "/api/runs", config)["run_id"]
            print(f"START {label} {run_id}", flush=True)
            deadline = time.monotonic() + 1100
            previous = None
            while True:
                state = request(args.base + "/api/runs/" + run_id)
                progress = (state["status"], state["phase"], len(state["attempts"]))
                if progress != previous:
                    print(f"  {label}: {progress}", flush=True)
                    previous = progress
                if state["status"] in TERMINAL:
                    break
                if time.monotonic() > deadline:
                    state = request(args.base + "/api/runs/" + run_id + "/cancel", {})
                    break
                time.sleep(.75)
            trace = traces / f"{label}-{run_id}.json"
            trace.write_text(json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            summary["runs"].append({"run_id": run_id, "provider": "ollama", "model": args.model, "flow": "auto", "mode": "live", "seeded": seeded, "preset": preset, "status": state["status"], "attempts": len(state["attempts"]), "duration_ms": state["metrics"]["duration_ms"], "generation_ms": state["metrics"]["generation_ms"], "trace": trace.relative_to(ROOT).as_posix(), "failures": [{"attempt": a["number"], "type": (a.get("error") or {}).get("type"), "message": (a.get("error") or {}).get("message"), "validation": (a.get("validation") or {}).get("passed")} for a in state["attempts"] if a["status"] != "success"]})
            output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"DONE {label}: {state['status']} / {len(state['attempts'])} attempts / {state['metrics']['duration_ms']} ms", flush=True)


if __name__ == "__main__":
    main()
