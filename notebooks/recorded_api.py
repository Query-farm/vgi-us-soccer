"""Serve exact, attributed ASA captures through the worker's supported API override."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class AsaSource:
    """Select explicit recorded or live mode, restoring inherited overrides on close."""

    def __init__(self, mode: str):
        if mode not in {"recorded", "live"}:
            raise ValueError("DATA_MODE must be recorded or live")
        self.mode = mode
        directory = Path(__file__).resolve().parent / "fixtures"
        self.manifest = json.loads((directory / "provenance.json").read_text())
        self.requests = []
        self.server = None
        self.previous = {
            name: os.environ.pop(name, None)
            for name in ("US_SOCCER_ASA_BASE_URL", "US_SOCCER_MLS_BASE_URL", "US_SOCCER_NWSL_BASE_URL")
        }
        bodies = {}
        for item in self.manifest["responses"]:
            body = (directory / item["file"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise ValueError(f"Changed recording: {item['file']}")
            bodies[item["path"]] = (body, {k: [v] for k, v in item["parameters"].items()})
        if mode == "recorded":
            owner = self

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    request = urlparse(self.path)
                    if request.path not in bodies:
                        self.send_error(404, "Outside recorded ASA routes")
                        return
                    body, expected = bodies[request.path]
                    if parse_qs(request.query) != expected:
                        self.send_error(400, "Only the documented 2025 regular-season request is recorded")
                        return
                    owner.requests.append(request.path)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            os.environ["US_SOCCER_ASA_BASE_URL"] = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        """Stop loopback replay and restore only this helper's environment settings."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
