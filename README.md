# ClimeProof Geospatial Pipeline

Given any U.S. address or coordinates, this tool produces a structured profile of its
environmental-hazard exposure using recent data from public datasets. Each metric in the
work-scope schema has a value, status, and provenance. This is all deterministic and repeatable.

---

## Quick start

Python ≥ 3.11. [uv](https://docs.astral.sh/uv/) is recommended (it gives a lockfile for
reproducible installs); plain `pip` works too.

```bash
uv venv && uv pip install -e ".[dev,wildfire]"     # or: python -m venv .venv && .venv/Scripts/pip install -e ".[dev,wildfire]"
```

```bash
climeproof catalog --implemented                   # what is computed so far, and from where
climeproof profile --lat 33.4484 --lon -112.0740   # one point -> JSON record on stdout
climeproof profile "350 S 5th St, Minneapolis, MN 55415"
climeproof batch data/inputs/examples/public_landmarks.csv --out-dir outputs/demo
climeproof compare --lat 33.4484 --lon -112.0740   # cross-source QC for extreme-heat day counts
pytest                                             # offline unit tests
pytest -m live                                     # smoke test against the real APIs
```

`--offline` reruns from the raw-response cache only. `--refresh` ignores the cache and refetches.
The `wildfire` extra (icechunk/xarray/zarr) is only needed for the Open Climate Risk fields;
without it those fields come back as `ERROR` with an install hint.

## Output

`batch` writes these files to the output folder:

| file | contents |
|---|---|
| `records.jsonl` | one full record per location (nested provenance), the canonical output |
| `metrics_long.csv` | one row per location × metric, with source/version/station/hash columns |
| `metrics_wide.csv` | one row per location, one column per metric (value, or the status) |
| `summary.jsonl` | one short client-facing summary per location (see below) |
| `unplaced.csv` | rows that could not be geocoded, with the reason (only if any) |

**Client summary.** `summary.jsonl` (or `profile --summary FILE` for one point) is derived from
the full record and adds nothing to it. It drops `NOT_IMPLEMENTED` metrics, keeps `NO_DATA`,
`N/A` and `ERROR` with their note, rounds values for reading, and cuts provenance down to a
source key (listed once under `sources`) plus the station name, id and distance for
station-based metrics. Requests, hashes and retrieval times stay in the full record.
`climeproof summarize FILE` builds summaries from an existing `.json` / `records.jsonl` without
rerunning anything.

Every record contains **every** metric in [`catalog.py`](src/climeproof/catalog.py), in the same
order, so records are directly comparable. Each value has one status:

| status | meaning |
|---|---|
| `OK` | value present, provenance attached |
| `N/A` | hazard does not apply here (e.g. storm surge inland) |
| `NO_DATA` | hazard could apply, but no public dataset covers this location. **A gap the assessment needs to see.** |
| `NOT_IMPLEMENTED` | the pipeline doesn't compute this yet. Development-only; must be zero at handoff |
| `ERROR` | a source failed for this location; `note` says why. Rerun, don't interpret |

## Current coverage

20 of 77 catalog metrics are computed so far. Everything else is emitted as `NOT_IMPLEMENTED`.
`climeproof catalog --implemented` always lists the current set.

**Climate metrics describe the recent climate**: the mean over the most recent 15 complete
calendar years. For a run in October 2026 that's **2011–2025**. The window moves forward each
January, and every value's `period` field states the exact years it used.

| hazard | metrics | source and window |
|---|---|---|
| Heat | days ≥ 90 / 100 / 105 °F, cooling degree days, heat-wave events/yr | ACIS GridData, PRISM grid at the point, recent 15 yr |
| Heat | trend in ≥ 100 °F days | same, over the last 30 yr (1996–2025), since a trend needs a longer record |
| Heat / cold | record high, record low | ACIS StnData: nearest active station with ≥ 30 yr of record, full record **through yesterday** |
| Cold | freeze days (≤ 32 °F), hard-freeze days (≤ 28 °F), days ≤ 0 °F, heating degree days | ACIS / PRISM, recent 15 yr |
| Winter storm | annual snowfall, days with snow depth ≥ 1 in | ACIS MultiStnData: nearest station with a complete recent record |
| Extreme precip | annual precip, days ≥ 1 in, mean annual max 1-day precip | ACIS / PRISM, recent 15 yr |
| Wildfire | burn probability (≈2011, ≈2047), risk to potential structures | CarbonPlan Open Climate Risk (30 m, CONUS), the latest edition |

PRISM is updated daily (ACIS currently serves data through yesterday). Because only complete
calendar years are averaged, a partial year never skews an annual count.

### Data sources

All sources are public and need no API key. How each is queried, and its known limitations:
[docs/sources.md](docs/sources.md).

| source | provides | coverage | used in |
|---|---|---|---|
| ACIS GridData: PRISM daily grid (~4 km) | heat and cold day counts, degree days, precipitation, heat-day trend, heat waves | CONUS | records |
| ACIS StnData / MultiStnData: GHCN-Daily stations | record high and low, snowfall, snow-depth days | stations within 50 km | records |
| CarbonPlan Open Climate Risk (30 m) | wildfire burn probability, risk to potential structures | CONUS | records |
| U.S. Census Geocoder | address to coordinates and county FIPS | U.S. | records (location) |
| NOAA NCEI U.S. Climate Normals 1991–2020 | long-term baseline for heat-day counts | stations within 50 km | `climeproof compare` only |
| NASA/ORNL Daymet V4 (1 km) | independent cross-check of heat-day counts | North America, HI, PR | `climeproof compare` only |

The NOAA Normals are the latest NOAA edition (the next is due around 2031), but they describe a
period centred on ~2005, so they serve only as a long-term reference next to the recent values.
The reasoning behind the first iteration's scope, and what comes next:
[docs/iteration-1-plan.md](docs/iteration-1-plan.md).

## Data windows and traceability

- **Recent by default.** `config/pipeline.toml` sets `periods.recent_years` (15) and
  `periods.trend_years` (30), both ending at the last complete calendar year. Records include
  observations up to yesterday. Each record's `run` block states the windows it used
  (`recent_period`, `trend_period`, `records_through`).
- **Traceable values.** Every raw response is cached under `data/cache/<source>/`. Each value's
  provenance carries the request and the response's sha256, so any number can be traced to the
  data it came from.
- **Re-creating an earlier run** (for an audit, say): set `periods.end_year` to that year and rerun.
  Records then stop at the end of that year too.
- **Versioned schema and config.** `schema.SCHEMA_VERSION`, `pipeline.config_version` and the
  config's sha256 are written into every record. Thresholds such as "≥ 100 °F" are part of each
  metric's definition, in `catalog.py`.

## Repository layout

```
config/pipeline.toml          every tunable that can change an output
src/climeproof/
  catalog.py                  the full Section-4 metric schema (implemented or not)
  schema.py                   pydantic models: record, metric value, status, provenance
  http.py                     cached HTTP client (raw-response audit trail)
  geocode.py                  U.S. Census geocoder (single + batch up to 10k rows)
  inputs.py                   bulk CSV loading (coords / address components / one-line address)
  pipeline.py                 orchestration + JSONL/CSV writers
  climate_stats.py            pure statistics (means with coverage, trends, percentiles, runs)
  compare.py                  cross-source QC for heat-day counts
  providers/                  one module per data source
    base.py                   Provider / PointProvider contract
    acis.py                   PRISM grid stats, station records, station snow
    open_climate_risk.py      wildfire (vectorised over the batch)
    ncei_normals.py daymet.py reference / cross-check sources for `compare`
tests/                        offline unit tests (+ `-m live` smoke test)
data/inputs/examples/         public example inputs (civic landmarks only)
docs/                         sources, limitations, plan
```

## Adding a source / metric

1. Add the metric(s) to `catalog.py` with `provider="<name>"` (bump `SCHEMA_VERSION` if it's new).
2. Write `providers/<name>.py`: subclass `PointProvider` (one query per location) or `Provider`
   (vectorised over the whole batch, for gridded stores) and return a `MetricValue` for every
   metric you own. Use `NO_DATA`/`N/A` with a `note`, never omit a field.
3. Register the class in `providers/__init__.py`.
4. Add offline tests with a `FakeHttp` handler (see `tests/test_providers.py`), and document the
   source and its limitations in `docs/sources.md`.
5. Add the metric(s) to the [Current coverage](#current-coverage) table and update the count. A new
   source also goes in the [Data sources](#data-sources) table.

## Data handling

The pipeline is developed and tested on bulk public inputs only, such as county sets, national
facility datasets and public landmarks. Participating facilities' names, addresses and
coordinates never enter the repository. In-house runs read from `data/inputs/private/` and
write to `outputs/`; both, along with the raw-response cache in `data/cache/`, are git-ignored.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the working rules.
