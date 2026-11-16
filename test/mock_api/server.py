"""Serve the recorded upstream fixtures over HTTP for the SQL tests.

``ci/run-integration.sh`` starts this server, points the worker's base-URL
environment variables at it, and runs ``test/sql`` through DuckDB, so the
suite is hermetic. Prints ``PORT:<n>`` once listening.
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from fixture_routes import CACHE_CONTROL, FIXTURES, resolve  # noqa: E402


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        source, _, rest = urlparse(self.path).path.lstrip("/").partition("/")
        name = resolve(source, rest)
        if name is None:
            self.send_error(404)
            return
        body = (FIXTURES / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", CACHE_CONTROL[source])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    """Serve until killed."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    print(f"PORT:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
