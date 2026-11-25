# Changelog

All notable changes to this project are documented here.

## [0.3.0] - 2026-11-25

- Speaks VGI protocol 3.4: require vgi-python `>=0.55.2,<0.56`; uv.lock re-locked. This release
  needs Haybarn 2.0.1 (or stock DuckDB 2.0 with `INSTALL vgi FROM query_farm`): Haybarn 2.0.0
  loads a 3.3 `vgi` extension that cannot attach it.
- SQL tests run on haybarn-unittest 2.0.1rc3 (CI and Makefile).
- `serve` extra includes `vgi-python[http,oauth]`; the Docker image installs it, so the image runs in
  Orchard hosted mode (`VGI_ORCHARD_HOSTED=1` with VGI_JWT_ISSUER, VGI_JWT_AUDIENCE,
  VGI_JWT_JWKS_URI and VGI_SIGNING_KEY). The Docker HEALTHCHECK uses `HEAD /health`, which
  stays anonymous in hosted mode.

## [Unreleased]

## 0.2.2 (2026-11-16)

- Bump vgi-python to 0.52.2.
- Requires Python 3.14 (CI, Docker image and tooling moved to 3.14).
- CI runs the SQL tests over stdio, launch and HTTP transports.

## [0.2.1]

- Docs link to upstream sources (VGI183): the catalog documentation now links the data providers it reads.

## [0.2.0]

- Speaks VGI protocol 3.3 (vgi-python 0.51); requires the current VGI DuckDB
  extension (3.2 extensions are incompatible).
- CI lints with vgi-lint-check 2.5.0.

## [0.1.0]

- Initial release on VGI protocol 3.2 (vgi-python 0.50), linted with
  vgi-lint-check 2.2.0.
- `mls` schema over the official MLS Stats API: current standings, player and
  club statistics, a rolling schedule window, and competitions as tables;
  seasons, standings (overall/home/away/form), clubs, club and player season
  statistics, schedules by date range, match summary, lineups, key events,
  commentary, club and player box scores, and player match logs as functions.
  Covers MLS, MLS Cup Playoffs, MLS NEXT Pro, Leagues Cup, US Open Cup,
  Canadian Championship, and CONCACAF Champions Cup.
- `nwsl` schema over the official NWSL Sports Data Platform: current standings,
  player statistics, matches, and competitions as tables; seasons, standings,
  teams, team and player statistics, matches, match event feeds, and rosters.
- `asa` schema over American Soccer Analysis (CC BY-SA 4.0): player and team xG,
  game xG, goals added, team directory, and MLS salaries for MLS, NEXT Pro,
  NWSL, and the USL leagues.
- One HTTP chokepoint with timeouts, bounded retries for 429/5xx honoring
  `Retry-After`, redirect following, per-host pacing, an honest User-Agent, and
  a bounded in-process response cache; upstream `no-store` is never advertised
  as cacheable.
- Hermetic Haybarn end-to-end test over recorded fixtures, opt-in live tests,
  executable catalog examples, and check_sql-graded agent tasks.
