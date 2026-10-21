# Data sources: how each one is queried, and its known limitations

Status as of iteration 1 (2026-10). All sources are public and need no API key.

**Data windows** (`config/pipeline.toml` → `periods`):
- **Climate statistics** use the most recent 15 complete calendar years, ending last year. That's
  2011–2025 for a run in 2026.
- **Trends** use the last 30 complete years (1996–2025).
- **Record highs/lows** use each station's full record, through yesterday.

## Used in iteration 1

### ACIS (Applied Climate Information System): GridData, StnData, MultiStnData
- **What:** RCC-ACIS web services.
  - GridData serves daily gridded products at a point with server-side reductions. Grid `21` is
    **PRISM**, which ACIS returns on a 1/24° (~4 km) lattice and updates daily.
  - StnMeta, StnData and MultiStnData serve GHCN-Daily-based station data.
- **How:**
  - **Annual reductions over the recent window, in one request** (`maxt cnt_ge_90/100/105`,
    `mint cnt_le_32/28/0`, `cdd sum`, `hdd sum`, base 65 °F, `pcpn sum`, `pcpn cnt_ge_1.00`,
    `pcpn max`). The pipeline then averages over years, needing ≥ 90 % valid years.
  - **Trend:** annual `maxt cnt_ge_100` over the 30-year trend window, then an OLS slope per decade.
  - **Heat waves:** daily Tmax over the recent window (definition below).
  - **Record high/low:** the nearest station within 50 km whose Tmax **and** Tmin records span
    ≥ 30 years and are still reporting in the last complete year. Full period of record, through
    yesterday.
  - **Snow:** one MultiStnData request returns the recent annual snowfall and snow-depth-day series
    of every station in the search box. Years with > 15 missing days count as missing. Each metric
    takes the nearest station (≤ 50 km) with ≥ 90 % complete years.
- **Limitations:**
  - **PRISM (grid 21) covers CONUS only.** For a point outside the domain, ACIS does *not* return an
    error: it silently answers with some other cell. Honolulu got a North Dakota cell, which
    produced "162 hard-freeze days/yr". The provider therefore rejects any response whose cell is
    more than 10 km from the requested point, and returns `NO_DATA`. **AK, HI and the territories
    currently have no gridded heat/cold/precip metrics**. Daymet, which covers HI and PR, is the
    candidate to fill that gap.
  - **15 years is a short sample for rare days.** A count like "days ≥ 105 °F" can vary noticeably
    from one 15-year window to the next. The window length is a config choice
    (`periods.recent_years`), and the data/science side should confirm it.
  - **Record extremes depend on which station is chosen.** Denver City Hall picks Lowry AFB (record
    102 °F), while Denver International Airport's record is 105 °F. ACIS also serves ThreadEx
    "threaded" city records, which may be a better fit for "record high"; that's a data/science
    decision. Records are also sensitive to station moves and instrument changes.
  - **Snow is station-based and patchy.** Volunteer (CoCoRaHS) stations are dense but often
    incomplete, which is why the provider scans every station in the box. In deserts snow depth
    is often unreported: Phoenix-area stations report 0 but miss years, so the result is `NO_DATA`
    there.
  - Station selection for records uses ACIS `valid_daterange` (first to last observation), which
    doesn't measure gaps within the record.
  - Grid elevation is returned in feet and converted to metres.
  - **Provisional heat-wave definition:** ≥ 3 consecutive days with Tmax ≥ the location's own 95th
    percentile of daily Tmax over the recent window. This needs data/science sign-off.
- **Checking values by hand:** https://xmacis.rcc-acis.org/ (single station → Monthly Summarized
  Data → number of days, with a threshold).

### CarbonPlan Open Climate Risk (OCR)
- **What:** 30 m CONUS wildfire tensors derived from USFS burn probability: `bp_2011`, `bp_2047`
  (annual burn probability), `rps_2011` (risk to a generic potential structure), and others.
  Licence: CC-BY-4.0. Docs: https://docs.carbonplan.org/ocr/
- **How:** the Icechunk repository on Source Cooperative (anonymous S3), opened with
  xarray + zarr, taking the nearest 30 m cell. The **snapshot id is pinned** in config.
- **Limitations:**
  - CONUS only. Points in AK, HI and the territories return `NO_DATA`.
  - Chunks are 6000 × 4500 cells, so one point costs roughly 30–60 s of transfer. Batches are extracted
    in one vectorised selection, so each chunk is read only once, and each point is memoised in the cache.
  - Empty cells (non-burnable / water) return `NO_DATA`. Risk is for a hypothetical generic structure,
    not the actual building.
  - The current-conditions layer represents circa 2011. The future layer is circa 2047, from a single
    scenario.

### U.S. Census Geocoder
- **What:** address → coordinates + county FIPS. One-line endpoint, and a batch endpoint
  (≤ 10k rows per request).
- **Limitations:** the benchmark `Public_AR_Current` changes over time. It is recorded in
  provenance, and the cache freezes results. Rural route / PO-box style addresses often fail to
  match; these go to `unplaced.csv` and need coordinates from the input dataset instead.

## Reference / cross-check only (`climeproof compare`)

### NOAA NCEI U.S. Climate Normals 1991–2020 (annual/seasonal)
- **Why reference only:** this is the latest NOAA edition (the next, 2001–2030, is due around 2031),
  so it describes a period centred on ~2005. It's kept as the long-term baseline that recent values
  are compared against.
- **How:** NCEI Search Service bbox query → stations and the data types each carries. Each data
  type comes from the nearest station that carries it (≤ 50 km), with values from the NCEI Data
  Service. Version is parsed from the archive name (`v1.0.1`).
- **Limitations:** station-based. The highest Tmax threshold is ≥ 100 °F (there is no ≥ 105 °F).
  Special values: `-7777` (trace) is read as 0, and the others are read as missing.

### NASA/ORNL Daymet V4 R1
- **What:** 1 km daily Tmax/Tmin/precip/SWE. The Single Pixel API returns a CSV per point. Currently
  available through 2025.
- **Use:** an independent gridded estimate of heat-day counts over the same recent window.
- **Limitations:** 365-day years (Dec 31 dropped in leap years). Interpolation smooths extremes.
  The newest year is added with a lag of several months.

## Evaluated, deferred to a later iteration

| source | why deferred | when it becomes worth it |
|---|---|---|
| **GHCN-Daily direct** (NCEI / AWS `noaa-ghcn-pds`) | ACIS already serves GHCN-D station data with server-side reductions | bulk station analytics, custom QC flags, or if ACIS availability becomes a risk |
| **nClimGrid-daily** (NetCDF, 1/24°) | point access means downloading monthly CONUS files | bulk mode: download once, then sample thousands of points locally. Also a third interpolation for cross-checks |
| **PRISM direct** (4 km / 800 m COG) | ACIS grid 21 already gives PRISM at a point | 800 m resolution for complex terrain, via bulk COG sampling |

## Gaps the scope names that these sources cannot fill
- **ASHRAE design conditions** (design high/low) are licensed, not public. Candidate public proxy:
  percentiles of daily Tmax/Tmin from the same gridded series. Needs sign-off before use.
- **Ice accumulation, snow load, blizzards** → FEMA NRI (county-level), ASCE hazard tool (snow load).
- **Rainfall return periods** → NOAA Atlas 14 PFDS (has a point API; a good next provider).
