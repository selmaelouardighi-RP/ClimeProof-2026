# Iteration 1: approach and roadmap

## Principle
Build the **whole skeleton once**, then add sources one at a time:

1. The complete Section-4 schema exists from day 1 (`catalog.py`), so every record has every
   field. Unbuilt fields read `NOT_IMPLEMENTED`, which turns "how close are we to handoff?" into a
   count.
2. Provenance, caching and reproducibility live in the framework (`http.py`, `schema.py`), not in
   each source. A new source gets them for free.
3. Iteration 1 fills the hazards with the **easiest, most available** data: point-queryable REST
   APIs with no key that compute statistics server-side (ACIS), plus one cloud-native
   gridded store (Open Climate Risk) that proves the batch-vectorised pattern.

## Why these sources first
- **Recent data first.** The record describes the climate a facility faces now: the most recent
  15 complete years (2011–2025 today), a 30-year trend, and records up to yesterday. That rules out
  NOAA's 1991–2020 Normals as a primary source, since it is centred on ~2005 and its next edition
  isn't due until ~2031. The Normals are kept in `climeproof compare` as the long-term baseline.
- **ACIS GridData (PRISM)** carries almost all the climate metrics: day counts at 90/100/105 °F
  and 32/28/0 °F, degree days, precipitation totals and extremes, trends and heat waves.
  - It is updated daily.
  - Because it is gridded at the exact point, there is no station-distance problem.
  - Server-side reductions keep each location to three small requests.
- **ACIS station data** supplies what only stations measure: record highs/lows, plus snowfall and
  snow cover (PRISM has no snow). For snow, one MultiStnData request scans every nearby station and
  picks the nearest one with a complete recent record.
- **Open Climate Risk** provides wildfire burn probability that has already been modelled. Its
  30 m data needs a batch-vectorised reader, and building one now sets the pattern for later raster
  sources (FEMA NFHL, USGS seismic, …).
- **Daymet + NRCC + Normals** in `climeproof compare` give the data/science side a quick view of
  how much sources disagree, and of how far recent years have shifted from 1991–2020.
  - At Phoenix City Hall, days ≥ 100 °F were 104.8/yr in 2011–2025, against 101.2/yr in 1991–2020
    (both PRISM).
  - Over the same recent years the sources differ: 104.8 (PRISM), 80.2 (NRCC), 112.2 (Daymet).

## Python stack, and why
| need | choice | notes |
|---|---|---|
| packaging / env | `pyproject.toml` + **uv** | lockfile = reproducible installs. Plain pip also works |
| HTTP | `requests` + urllib3 `Retry` | simple, and thread-safe with per-thread sessions |
| schema / validation | **pydantic v2** | enforces status ⇔ value ⇔ provenance consistency, and does JSON I/O |
| CLI | `typer` | |
| gridded / cloud data | `xarray` + `zarr` + `icechunk` (optional extra) | the native stack for OCR. Covers NetCDF (nClimGrid) later too |
| tests / lint | `pytest`, `ruff` | |
| **later** | `geopandas`/`shapely` (polygon hazards: FEMA flood zones), `rioxarray`/`rasterio` (COG rasters: PRISM 800 m, USGS), `pandas` (bulk analysis) | added only when a source needs them |

The core deliberately has no pandas, GDAL or numpy: point APIs don't need them, and they are
the most common cause of installation failures on Windows.

## Decisions needed from the data/science side
1. Heat-wave definition (currently provisional: ≥ 3 days ≥ local p95 Tmax).
2. Maximum station distance for station-based metrics (50 km now). Should an elevation
   difference limit be added?
3. Whether a public proxy for design conditions (e.g. 99.6 % / 0.4 % percentiles) is acceptable, or
   whether the field should stay `NO_DATA`.
4. Primary gridded source. PRISM is the default; `climeproof compare` shows NRCC and Daymet
   alongside it, and they can disagree by 20+ days/yr at hot locations.
5. Length of the recent window (15 yr now). Shorter tracks the current climate more closely but is
   noisier for rare days such as ≥ 105 °F. Longer is more stable but more dated.
6. Record highs/lows: nearest long-record station (current), or ThreadEx threaded city records?
7. Gridded source outside CONUS (AK/HI/PR), where PRISM has no coverage: Daymet?

## Suggested next iterations
- **Bulk public input loader** for a national hospital point dataset (e.g. CMS Hospital General
  Information, or a successor to HIFLD hospitals). Also county sets for the county-level layers.
- **County-level layer:** FEMA National Risk Index (ice storm, winter weather, hail, tornado,
  hurricane, wildfire, plus community resilience and expected annual loss), and CDC/ATSDR SVI. Both are
  joined on the `county_fips` / tract the geocoder already returns.
- **Point rasters / APIs:** NOAA Atlas 14 PFDS (return periods), the USGS seismic design API (PGA),
  and FEMA NFHL (flood zone, a point-in-polygon query).
- **Applicability rules** for `N/A` (coastal/surge/tsunami inland, volcanic outside the western
  U.S./AK/HI), driven by public boundary datasets rather than hand lists.
