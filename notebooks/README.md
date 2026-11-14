# US Soccer notebooks

| Notebook | Question | Default / experiment |
|---|---|---|
| [Minutes threshold and finishing](01_minutes_threshold_and_finishing.ipynb) | How does eligibility change a player-team comparison of goals and ASA expected goals per 90? | 900 → 1,800 minutes; 2025 MLS regular season |

The executed example uses **recorded public American Soccer Analysis data**, not synthetic players or the official MLS/NWSL APIs. Three original JSON responses, captured independently on 2026-11-14 UTC, include 882 player-team metric lines and the name directories. Their exact requests, timestamps, byte hashes and counts are in [provenance](fixtures/provenance.json). The source data and derived tables/charts are attributed to **American Soccer Analysis (americansocceranalysis.com), CC BY-SA 4.0**; see [data license](fixtures/LICENSE.md). The repository code license is separate.

## Run from this directory alone

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then copy or download the complete `notebooks/` directory. No repository source, local worker build or root environment is needed. First use needs internet access for dependencies, the community VGI extension and the pinned public Git worker; live mode also needs ASA connectivity. Python 3.13 is used for the worker; uv can provision it. The notebook environment supports Python 3.13–3.14.

```sh
cd notebooks
uv sync --frozen
uv run --frozen python execute.py
uv run --frozen python execute.py --parameters '{"MIN_MINUTES":1800}' --output-dir validation/minutes-1800
uv run --frozen python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir validation/live
```

The runner creates a temporary kernel, executes from this directory and writes only after successful execution. Overrides require a separate output directory. Experiment copies include helpers, assets, data, documentation and the lockfile. Generated validation logs/charts are ignored; default outputs are embedded in the committed notebook.

For Jupyter, install a named kernel after syncing, select it, then restart and run all:

```sh
uv run --frozen python -m ipykernel install --user --name us-soccer-notebooks --display-name 'Python (US Soccer notebooks)'
```

The visible SQL `ATTACH` uses public Git revision `823758963106e522f74ced2eb8f1eebaa1338b5b` with `vgi-python==0.51.0`, `vgi-rpc==0.53.1`, `httpx==0.28.1` and `pyarrow==25.0.1`. It was executed through published Haybarn `2.0.0rc11`. Upgrading the revision or pins requires rerunning both parameter cases and the live check; changing the notebook lock does not automatically change the literal worker pin.

## Source modes and interpretation

`DATA_MODE="recorded"` starts a disposable loopback server that serves only the three exact captured requests using the worker's supported `US_SOCCER_ASA_BASE_URL`. The real worker performs HTTP retrieval, directory joins, type conversion and VGI transport. Hashes are checked before use. `DATA_MODE="live"` disables inherited source overrides and uses ASA's official HTTPS API, with no fallback. The helper restores prior overrides at cleanup. The connection has an empty temporary secret directory with persistent secrets disabled.

`MIN_MINUTES` accepts whole values 90–2,500. The API minimum stays zero; SQL makes availability and eligibility visible. The key is **player ID plus team ID**, so transferred players are not silently combined. Missing measurements are excluded and reported, never converted to zero. The pooled gap is minutes-weighted; it is not an unweighted average of rates. Source rounded values are reconciled within 0.0002 goals.

The scatterplot keeps its axes fixed across cutoff changes; the extreme-gap bar chart uses its own explicitly labeled scale. Extremes are selected deliberately and are not a representative sample. These descriptive aggregates lack shot-level uncertainty and do not prove persistent skill, causality or predictive value. Live data and name directories can change independently; the capture is not an atomic snapshot. No official MLS/NWSL data is redistributed here.
