# ASA data attribution and license

Data: **American Soccer Analysis (americansocceranalysis.com)**.

The bundled JSON responses (`xgoals.json`, `players.json`, `teams.json`) and derived notebook data tables and charts are licensed under **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**:

- Source: https://www.americansocceranalysis.com/
- API: https://app.americansocceranalysis.com/api/v1/
- License: https://creativecommons.org/licenses/by-sa/4.0/
- Legal text: https://creativecommons.org/licenses/by-sa/4.0/legalcode

The responses preserve their original public API bytes. `provenance.json` identifies each exact request, independent capture timestamp, row count and SHA-256. Notebook transformations join source names, classify minutes eligibility, calculate per-90 rates and select extreme gaps; these changes are described in the visible SQL. The analysis is by Query.Farm and does not imply ASA endorsement. Share derived data or charts under the same license and retain this attribution, license link and indication of changes. Code remains under the repository's code license.
