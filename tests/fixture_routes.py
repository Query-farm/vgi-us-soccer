"""Map upstream request paths to the recorded responses in ``tests/fixtures``.

The same routing serves the in-process ``httpx.MockTransport`` used by unit tests
and the local HTTP server used by the hermetic Haybarn end-to-end test. Paths
are relative to each source's base URL.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_ROUTES: dict[str, list[tuple[str, str]]] = {
    "mls": [
        (r"^competitions$", "mls_competitions.json"),
        (r"^competitions/[^/]+/seasons$", "mls_seasons.json"),
        (r"^competitions/[^/]+/seasons/[^/]+/standings$", "mls_standings.json"),
        (r"^clubs/competitions/[^/]+/seasons/[^/]+$", "mls_clubs.json"),
        (r"^statistics/clubs/competitions/[^/]+/seasons/[^/]+$", "mls_club_stats.json"),
        (r"^statistics/players/competitions/[^/]+/seasons/[^/]+$", "mls_player_stats.json"),
        (r"^matches/seasons/[^/]+$", "mls_schedule.json"),
        (r"^matches/MLS-MAT-[0-9A-Z]{6}/key_events$", "mls_key_events.json"),
        (r"^matches/MLS-MAT-[0-9A-Z]{6}/commentary$", "mls_commentary.json"),
        (r"^matches/MLS-MAT-0009NL$", "mls_match.json"),
        (r"^statistics/clubs/matches/[^/]+$", "mls_match_club_stats.json"),
        (r"^statistics/players/matches/[^/]+$", "mls_match_player_stats.json"),
        (r"^statistics/players/MLS-OBJ-[0-9A-Z]{6}/matches$", "mls_player_match_log.json"),
    ],
    "nwsl": [
        (r"^competitions$", "nwsl_competitions.json"),
        (r"^competitions/[^/]+/seasons$", "nwsl_seasons.json"),
        (r"^seasons/[^/]+/standings/overall$", "nwsl_standings.json"),
        (r"^seasons/[^/]+/teams$", "nwsl_teams.json"),
        (r"^seasons/[^/]+/stats/players$", "nwsl_player_stats.json"),
        (r"^seasons/[^/]+/stats/teams$", "nwsl_team_stats.json"),
        (r"^seasons/[^/]+/matches$", "nwsl_matches.json"),
        (r"^seasons/[^/]+/matches/[^/]+/feed$", "nwsl_feed.json"),
        (r"^teams/[^/]+/roster$", "nwsl_roster.json"),
    ],
    "asa": [
        (r"^mls/players/xgoals$", "asa_mls_players_xgoals.json"),
        (r"^mls/players/goals-added$", "asa_mls_players_goals_added.json"),
        (r"^mls/players/salaries$", "asa_mls_players_salaries.json"),
        (r"^mls/teams/xgoals$", "asa_mls_teams_xgoals.json"),
        (r"^mls/games/xgoals$", "asa_mls_games_xgoals.json"),
        (r"^mls/teams$", "asa_mls_teams.json"),
        (r"^mls/players$", "asa_mls_players.json"),
    ],
}

# Upstream cache headers observed while recording: MLS sends no-store, the NWSL
# platform a day-long private max-age, and ASA a bare ``private``.
CACHE_CONTROL = {"mls": "no-store", "nwsl": "private, max-age=86400", "asa": "private"}


def load(name: str) -> Any:
    """Return one decoded fixture."""
    return json.loads((FIXTURES / name).read_text())


def resolve(source: str, path: str) -> str | None:
    """Return the fixture filename for ``path`` under ``source``, or None for a 404."""
    for pattern, name in _ROUTES.get(source, []):
        if re.match(pattern, path.strip("/")):
            return name
    return None
