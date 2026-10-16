"""Open the local AutoHeal dashboard without a manual server command."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"


def ready():
    try:
        with urllib.request.urlopen(URL + "/api/status", timeout=1) as response:
            return json.load(response).get("service") == "autoheal-studio"
    except Exception:
        return False


def main():
    if ready():
        webbrowser.open(URL)
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ollama = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1).close()
    except Exception:
        if Path(ollama).is_file():
            subprocess.Popen([ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    runtime = ROOT / "autoheal" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "server.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "autoheal.server"], cwd=ROOT, stdout=log, stderr=log, creationflags=flags)
    for _ in range(40):
        if ready():
            webbrowser.open(URL)
            return
        if process.poll() is not None:
            break
        time.sleep(0.25)
    raise SystemExit("AutoHeal could not start. See autoheal/runtime/server.log; port 8765 may already be occupied.")


if __name__ == "__main__":
    main()
