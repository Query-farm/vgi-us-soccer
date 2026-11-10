"""Hermetic end-to-end coverage through Haybarn and the VGI transport.

A local HTTP server replays the recorded upstream responses for all three
sources; the worker is pointed at it through its base-URL environment variables
and attached exactly as a user would attach it.
"""

from __future__ import annotations

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from fixture_routes import CACHE_CONTROL, FIXTURES, resolve


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


TABLES = [
    "mls.current_standings",
    "mls.current_player_stats",
    "mls.current_club_stats",
    "mls.current_schedule",
    "mls.competitions",
    "nwsl.current_standings",
    "nwsl.current_player_stats",
    "nwsl.current_matches",
    "nwsl.competitions",
]


def test_haybarn_attaches_and_queries_every_current_table() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = Path(__file__).resolve().parent.parent
    location = f"uv run --project {project} vgi-us-soccer"
    counts = ", ".join(
        f"(SELECT count(*) FROM us_soccer.{table}) AS {table.replace('.', '_')}" for table in TABLES
    )
    sql = (
        f"INSTALL vgi FROM community; LOAD vgi; ATTACH 'us_soccer' (TYPE vgi, LOCATION '{location}'); "
        f"SELECT {counts}; "
        "SELECT home_club_abbreviation, home_goals, away_goals, away_club_abbreviation "
        "FROM us_soccer.mls.match('MLS-MAT-0009NL'); "
        "SELECT player_name FROM us_soccer.mls.match_events('MLS-MAT-0009NL') WHERE is_goal "
        "ORDER BY event_time; "
        "SELECT count(*) AS asa_teams FROM us_soccer.asa.xg_teams(season := 2026);"
    )
    base = f"http://127.0.0.1:{server.server_port}"
    env = {
        **os.environ,
        "US_SOCCER_MLS_BASE_URL": f"{base}/mls",
        "US_SOCCER_NWSL_BASE_URL": f"{base}/nwsl",
        "US_SOCCER_ASA_BASE_URL": f"{base}/asa",
    }
    try:
        result = subprocess.run(
            ["uvx", "haybarn-cli", ":memory:", "-csv", "-c", sql],
            cwd=project,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    lines = result.stdout.splitlines()
    header = ",".join(table.replace(".", "_") for table in TABLES)
    assert header in lines
    assert lines[lines.index(header) + 1] == "4,3,3,4,19,3,3,3,4"
    assert "CIN,0,2,CLB" in lines
    assert lines[lines.index("player_name") + 1 : lines.index("player_name") + 3] == [
        "Gonzalo Tapia",
        "Taha Habroune",
    ]
    assert lines[lines.index("asa_teams") + 1] == "3"
