"""Loopback-only dashboard and trace API; Python standard library only."""
import argparse
import json
import mimetypes
from pathlib import Path
import platform
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .engine import RunManager
from .presets import public_presets
from .provider import ollama_status

WEB_DIR = Path(__file__).resolve().parent / "web"
MANAGER = RunManager()
MAX_BODY = 32000


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoHeal/1.0"
    sys_version = ""

    def log_message(self, format, *args):
        # Source, task data, and model response must never enter access logs.
        pass

    def _headers(self, status, content_type="application/json; charset=utf-8", length=None, download=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()

    def _json(self, payload, status=200, download=None):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        self._headers(status, length=len(raw), download=download)
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _local_request(self, mutation=False):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            self._json({"error": "Only the local dashboard host is accepted."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in hosts}:
            self._json({"error": "Cross-origin requests are not accepted."}, 403)
            return False
        if mutation and self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json({"error": "Mutating requests require application/json."}, 415)
            return False
        return True

    def do_OPTIONS(self):
        self._json({"error": "Cross-origin access is disabled."}, 403)

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            self._json({"service": "autoheal-studio", **ollama_status(), "python": platform.python_version(), "safety": "Defense-in-depth constrained subprocess, not a hard OS security sandbox. Local trusted demonstrations only.", "limits": {"max_attempts": 5, "max_execution_seconds": 5, "max_output_characters": 16000, "max_code_characters": 24000, "memory_mb": 384, "memory_limit": "Windows Job Object; best effort, per-attempt active flag in trace"}, "version": "1.0.0"})
            return
        if path == "/api/presets":
            self._json({"presets": public_presets()})
            return
        match = re.fullmatch(r"/api/runs/([a-f0-9]{16})(/export)?", path)
        if match:
            state = MANAGER.snapshot(match.group(1))
            if state is None:
                self._json({"error": "Run not found or removed from the bounded history."}, 404)
            else:
                self._json(state, download=f"autoheal-{state['id']}.json" if match.group(2) else None)
            return
        if path.startswith("/api/"):
            self._json({"error": "Unknown API route."}, 404)
            return
        if path == "/":
            path = "/index.html"
        file = (WEB_DIR / path.lstrip("/")).resolve()
        if not file.is_relative_to(WEB_DIR.resolve()) or not file.is_file():
            self._json({"error": "File not found."}, 404)
            return
        raw = file.read_bytes()
        kind = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in {"application/javascript", "application/json"}:
            kind += "; charset=utf-8"
        self._headers(200, kind, len(raw))
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self._local_request(mutation=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY:
                self._json({"error": "Request body exceeds the 32 KB limit."}, 413)
                return
            body = self.rfile.read(length)
            config = json.loads(body or b"{}")
        except (ValueError, UnicodeError):
            self._json({"error": "Request body must be valid JSON."}, 400)
            return
        path = urlsplit(self.path).path
        if path == "/api/runs":
            try:
                run_id = MANAGER.create(config)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"run_id": run_id}, 202)
            return
        match = re.fullmatch(r"/api/runs/([a-f0-9]{16})/cancel", path)
        if match:
            state = MANAGER.cancel(match.group(1))
            self._json(state if state else {"error": "Run not found."}, 200 if state else 404)
            return
        self._json({"error": "Unknown API route."}, 404)


def serve(host="127.0.0.1", port=8765):
    if host != "127.0.0.1":
        raise ValueError("AutoHeal accepts only the IPv4 loopback host 127.0.0.1.")
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"AutoHeal Studio is ready at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoHeal Studio local dashboard")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(port=args.port)
