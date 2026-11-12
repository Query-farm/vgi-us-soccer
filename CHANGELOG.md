# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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
