<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-kalshi/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-us-soccer</h1>

<p align="center">
  MLS, NWSL, MLS NEXT Pro, and USL standings, schedules, statistics, and xG as ordinary DuckDB tables.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-us-soccer/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-us-soccer/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-read--only-6f42c1.svg" alt="Read-only VGI worker"></a>
</p>

---

`vgi-us-soccer` fetches data on demand from three public, keyless sources:

- The official MLS Stats API covers MLS, the MLS Cup Playoffs, MLS NEXT Pro,
  Leagues Cup, the US Open Cup, the Canadian Championship, and the CONCACAF
  Champions Cup.
- The official NWSL Sports Data Platform covers the NWSL.
- American Soccer Analysis (ASA) provides xG, goals added, and salaries for
  MLS, NEXT Pro, the NWSL, and the USL leagues.

The worker reformats each response as typed Arrow data for Haybarn SQL. It
needs no credentials, and it does not rehost or persist any dataset.

## Quick start

Install the released worker with `uv`:

```bash
uv tool install vgi-us-soccer
vgi-us-soccer
```

Launch Haybarn with the catalog pre-attached:

```bash
uvx haybarn-cli \
  -cmd "INSTALL vgi FROM community; LOAD vgi; ATTACH 'us_soccer' (TYPE vgi, LOCATION 'vgi-us-soccer');" \
  :memory:
```

Or attach it in an existing Haybarn session:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'us_soccer' (
  TYPE vgi,
  LOCATION 'vgi-us-soccer'
);
```

For source development, run `uv lock --check --no-sources`, then
`uv sync --no-sources` and `uv run --no-sources vgi-us-soccer`. The lockfile
resolves every dependency from package registries, so you don't need a
sibling checkout.

## Catalog surface

The catalog `us_soccer` has three schemas. The default schema is `mls`.

| Schema | Kind | Objects |
| --- | --- | --- |
| `mls` | Tables | `current_standings`, `current_player_stats`, `current_club_stats`, `current_schedule`, `competitions` |
| `mls` | Season functions | `seasons()`, `standings()`, `clubs()`, `club_stats()`, `player_stats()`, `schedule()` |
| `mls` | Match and player detail | `match()`, `match_lineups()`, `match_events()`, `match_commentary()`, `match_club_stats()`, `match_player_stats()`, `player_match_log()` |
| `nwsl` | Tables | `current_standings`, `current_player_stats`, `current_matches`, `competitions` |
| `nwsl` | Functions | `seasons()`, `standings()`, `teams()`, `team_stats()`, `player_stats()`, `matches()`, `match_events()`, `roster()` |
| `asa` | Functions | `teams()`, `xg_players()`, `xg_teams()`, `xg_games()`, `goals_added_players()`, `salaries()` |

Each `current_*` table and each `competitions` table reads from a
parameterless `all_*` scan function. The tables have declared primary keys.

## Usage

### MLS standings

```sql
SELECT position, club_name, games_played, points, goal_difference
FROM us_soccer.mls.current_standings
ORDER BY position;
```

The MLS Stats API publishes one league-wide table, which is the Supporters'
Shield order. It doesn't publish separate conference tables. `standings()` takes
a season year, a competition, and a `split` of `overall`, `home`, `away`, or
`form`. Standings go back to 1996:

```sql
-- Final 2025 regular-season table
SELECT position, club_name, points, goal_difference
FROM us_soccer.mls.standings(season := 2025)
ORDER BY position;

-- MLS NEXT Pro home table this season
SELECT position, club_name, wins, points
FROM us_soccer.mls.standings(competition := 'next_pro', split := 'home')
ORDER BY position;
```

`competition` accepts these aliases: `mls`, `mls_playoffs`, `next_pro`,
`next_pro_playoffs`, `leagues_cup`, `us_open_cup`, `canadian_championship`,
`champions_cup`, `campeones_cup`, and `all_star`. It also accepts any raw
`MLS-COM-` id from `mls.competitions`.

### Players, clubs, and schedules

```sql
-- Golden Boot race, with tracking-model xG
SELECT player_name, club_abbreviation, goals, assists, round(xg, 1) AS xg
FROM us_soccer.mls.current_player_stats
ORDER BY goals DESC
LIMIT 10;

-- 2025 clubs by expected goals and possession
SELECT club_name, goals, round(xg, 1) AS xg, possession_ratio
FROM us_soccer.mls.club_stats(season := 2025)
ORDER BY xg DESC;

-- Results on one matchday
SELECT match_id, home_club_abbreviation, home_goals, away_goals, away_club_abbreviation
FROM us_soccer.mls.schedule(
  season := 2026, competition := 'mls',
  start_date := DATE '2026-10-18', end_date := DATE '2026-10-18'
)
ORDER BY planned_kickoff;
```

Player statistics have one row per player and club. A player traded during a
season has a separate row for each club. `current_schedule` covers a rolling
window from seven days ago to fourteen days ahead, across every MLS-family
competition. It can be empty in the off-season. Scores are `NULL` until
kickoff.

### Match detail

Match functions take an `MLS-MAT-` id from `schedule()`:

```sql
SELECT home_club_name, home_goals, away_goals, away_club_name, attendance, referee
FROM us_soccer.mls.match('MLS-MAT-0009NL');

SELECT minute_of_play, club_abbreviation, player_name, other_player_name AS assist, xg
FROM us_soccer.mls.match_events('MLS-MAT-0009NL')
WHERE is_goal
ORDER BY event_time;

SELECT player_name, club_abbreviation, minutes_played, shots, round(xg, 2) AS xg
FROM us_soccer.mls.match_player_stats('MLS-MAT-0009NL')
ORDER BY xg DESC;

-- Lionel Messi's 2025 regular-season match log
SELECT planned_kickoff, match_title, minutes_played, goals, assists
FROM us_soccer.mls.player_match_log('MLS-OBJ-000396', season := 2025, competition := 'mls')
ORDER BY planned_kickoff;
```

### NWSL

You pass seasons as years. The worker looks up the platform's opaque ids
(`nwsl::Football_Season::<hex>`) from its competitions and seasons endpoints,
and never hard-codes them.

```sql
SELECT position, team_name, points, form, qualification
FROM us_soccer.nwsl.current_standings
ORDER BY position;

SELECT player_name, team_abbreviation, goals, assists, round(xg, 1) AS xg
FROM us_soccer.nwsl.player_stats(season := 2025)
ORDER BY goals DESC
LIMIT 10;

SELECT shirt_number, player_name, position_name, nationality
FROM us_soccer.nwsl.roster('GFC', season := 2026)
ORDER BY shirt_number;
```

### American Soccer Analysis

Every `asa` function takes these arguments:

- `league`: one of `mls`, `mlsnp`, `nwsl`, `uslc`, `usl1`, `usls`, or `nasl`.
- `season`: a year.
- `stage`: `regular_season` (the default), `playoffs`, or `all`.

Player metrics have one row per player and team. You can set
`minimum_minutes` to leave out players with few minutes.

```sql
SELECT player_name, team_abbreviation, goals, round(xgoals, 1) AS xg,
       round(goals_minus_xgoals, 1) AS diff
FROM us_soccer.asa.xg_players(season := 2025, minimum_minutes := 1500)
ORDER BY goals_minus_xgoals DESC
LIMIT 10;

SELECT player_name, team_abbreviation, round(goals_added_above_avg, 2) AS gplus
FROM us_soccer.asa.goals_added_players(league := 'nwsl', season := 2025, minimum_minutes := 1000)
ORDER BY goals_added_above_avg DESC
LIMIT 10;

SELECT team_name, points, round(xpoints, 1) AS xpts, round(xgoal_difference, 1) AS xgd
FROM us_soccer.asa.xg_teams(season := 2025)
ORDER BY xgoal_difference DESC;
```

## Data sources, licences, and affiliation

This project is **not affiliated with, endorsed by, or sponsored by** Major
League Soccer, the National Women's Soccer League, Opta/Stats Perform,
Sportec Solutions, or American Soccer Analysis. Team and league names are used
only to describe the data.

- **MLS Stats API** (`stats-api.mlssoccer.com`) is the official, undocumented
  backend behind mlssoccer.com. The data is © Major League Soccer, L.L.C. The
  mlssoccer.com terms prohibit scraping or harvesting its services for
  commercial purposes. This worker is for personal, non-commercial analysis. It
  fetches only what a query asks for, when the query runs, and it never stores
  or redistributes the data. Commercial use needs a licence from MLS.
- **NWSL Sports Data Platform** (`api-sdp.nwslsoccer.com`) is the official,
  undocumented widget backend behind nwslsoccer.com. The data is Opta-derived
  and © the NWSL and its data providers. The same posture applies: personal,
  non-commercial, on-demand access with no rehosting.
- **American Soccer Analysis** (`app.americansocceranalysis.com`) licenses its
  API data under
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). If you
  publish results from the `asa` schema, credit **American Soccer Analysis
  (americansocceranalysis.com)** and release any derived data under the same
  licence.

The MIT licence below covers this worker's code only. It grants no rights to
the upstream data.

## Production HTTP deployment

Stdio is the recommended transport when Haybarn can launch the worker
locally. Use HTTP when hosts must share the worker. The production HTTP
entry point fails closed: it needs a stable signing key, and either
authentication or an explicit decision to allow anonymous access:

```bash
export VGI_SIGNING_KEY='a-long-random-secret-shared-by-every-replica'
export VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn'

vgi-us-soccer-http \
  --host 0.0.0.0 \
  --port 8000 \
  --cors-origins 'https://sql.example.com' \
  --log-format json
```

`vgi-us-soccer-http` turns off description pages and cross-origin access
unless you configure them. Terminate TLS at a trusted proxy or load balancer.
Every replica must use the same `VGI_SIGNING_KEY`. Outstanding state tokens
are signed with that key, so rotate it as a coordinated deployment.

The supported authentication options are:

- `VGI_BEARER_TOKENS`: comma-separated `token=principal` pairs.
- `VGI_JWT_ISSUER` and `VGI_JWT_AUDIENCE`: JWT/JWKS authentication.
- `VGI_PROXY_PROOF_MODE=require`, plus the matching VGI proxy-proof settings,
  when a trusted proxy authenticates users.

`VGI_ALLOW_ANONYMOUS=1` turns on anonymous access. Before you use it, check
that your use fits the upstream terms above. Put a public service behind
gateway rate limits. The health probe is `GET /health`.

### Container

```bash
docker build -t vgi-us-soccer .
docker run --rm -p 8000:8000 \
  -e VGI_SIGNING_KEY='replace-with-a-stable-random-secret' \
  -e VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn' \
  vgi-us-soccer
```

The image runs as an unprivileged user and emits JSON logs. Description pages
are off, and the image includes a health check.

## Reliability and operations

All upstream traffic goes through a single module, `vgi_us_soccer/api.py`.
That module applies these limits:

- **Timeouts.** A request times out after 30 seconds, or 60 seconds for ASA,
  whose cold aggregate queries are slow. A whole query times out after 120
  seconds.
- **Retries.** A request gets at most four attempts. HTTP 429 and transient
  5xx responses are retried with jittered exponential backoff. `Retry-After` is
  honored, up to 30 seconds per retry.
- **Concurrency and pacing.** At most four upstream requests run at once in
  each process. Requests to the same host are spaced at least 100 ms apart
  (200 ms for ASA).
- **Redirects.** Redirects are followed.
- **User-Agent.** Every request sends
  `vgi-us-soccer/<version> (+https://github.com/Query-farm/vgi-us-soccer)`.
- **Response cache.** A bounded in-process cache keeps responses so that one
  SQL query, and queries close together, don't fetch the same document twice.
  Entries expire after the source's default TTL: 60 s for MLS, 120 s for NWSL,
  and 15 minutes for ASA. Competition, season, and directory lists are kept
  for an hour.

VGI clients get freshness metadata only when the upstream allows it. MLS sends
`Cache-Control: no-store`, so the worker advertises no cache lifetime to VGI
clients for MLS data. The NWSL platform's `max-age` is passed on, capped at
five minutes.

The MLS backend is undocumented. It changed shape in the 2024 Sportec
migration, which broke the legacy Opta-era routes. Every path is pinned in
`vgi_us_soccer/mls.py`, and contract tests cover each one. The worker leaves
out the API's internal "MLS Test" competition, which duplicates real matches.

For hermetic tests, three variables can point the worker at alternate roots:
`US_SOCCER_MLS_BASE_URL`, `US_SOCCER_NWSL_BASE_URL`, and
`US_SOCCER_ASA_BASE_URL`. Never set them from untrusted input.

## Development and release checks

```bash
uv lock --check --no-sources
uv sync --no-sources
uv run --no-sources ruff check .
uv run --no-sources ruff format --check .
uv run --no-sources pytest --cov=vgi_us_soccer --cov-fail-under=80
uv build
uvx twine check dist/*
uvx --no-sources --from vgi-lint-check==2.2.0 vgi-lint lint \
  'uv run --no-sources us_soccer_worker.py' \
  --no-execute --no-check-links --audit-waivers --fail-on warning
```

The offline suite includes a hermetic Haybarn end-to-end test. It replays the
recorded responses in `tests/fixtures/` from a local HTTP server and queries
every table through `INSTALL vgi FROM community; LOAD vgi;`.

The live upstream tests are opt-in: run `uv run pytest -m live`. They also run
on a serialized schedule, together with the executing catalog lint, in
`.github/workflows/live.yml`.

Releases are driven by GitHub releases. Create a release named `vX.Y.Z` that
matches the version in `pyproject.toml`. CI then builds, attests, and
validates the distributions, and publishes them through PyPI trusted
publishing and to GHCR.

---

Copyright 2026 Query Farm LLC - https://query.farm
