"""Cross-source check for extreme-heat day counts at one point (QC aid, not a record field).

Puts the record's source (PRISM via ACIS, recent years) next to an independent interpolation
(NRCC) and Daymet over the same recent years, plus the 1991-2020 long-term reference (NOAA
station normals and PRISM over 1991-2020), so both source disagreement and the shift between
the long-term normal and recent years are visible at a glance.
"""

from __future__ import annotations

from .climate_stats import mean_with_coverage
from .config import Settings
from .http import CachedHttp
from .providers.acis import (
    GRID_NAMES,
    MAX_GRID_CELL_OFFSET_KM,
    grid_cell_offset_km,
    grid_cell_ref,
    num,
)
from .providers.daymet import annual_mean_days_tmax_ge, fetch_daily
from .providers.ncei_normals import fetch_normals
from .schema import Location

THRESHOLDS = [90, 100, 105]
REFERENCE = (1991, 2020)  # latest NOAA normals period


def _acis_grid_row(
    loc: Location, settings: Settings, http: CachedHttp, grid: str, start: int, end: int
) -> dict:
    resp = http.post_json(
        "acis",
        f"{settings.acis.base_url}/GridData",
        {
            "loc": f"{loc.longitude:.5f},{loc.latitude:.5f}",
            "grid": grid,
            "meta": "ll",
            "sdate": str(start),
            "edate": str(end),
            "elems": [
                {"name": "maxt", "interval": "yly", "duration": "yly", "reduce": f"cnt_ge_{t}"}
                for t in THRESHOLDS
            ],
        },
    )
    d = resp.json()
    row = {"source": f"ACIS grid {grid} ({GRID_NAMES.get(grid, '?')})", "detail": f"{start}-{end}"}
    offset = grid_cell_offset_km(loc, grid_cell_ref(d.get("meta", {})))
    if offset is None or offset > MAX_GRID_CELL_OFFSET_KM:
        return {**row, "detail": "outside grid domain"}
    data = d.get("data", [])
    for i, t in enumerate(THRESHOLDS):
        row[t] = mean_with_coverage(
            [num(r[i + 1]) for r in data], settings.periods.min_year_coverage
        )
    return row


def compare_heat_days(loc: Location, settings: Settings, http: CachedHttp) -> list[dict]:
    per = settings.periods
    rows: list[dict] = [
        _acis_grid_row(loc, settings, http, settings.acis.grid, per.recent_start, per.recent_end),
        _acis_grid_row(loc, settings, http, "1", per.recent_start, per.recent_end),
    ]
    try:
        daily, _ = fetch_daily(http, settings, loc.latitude, loc.longitude, "tmax")
        years = sorted({int(r["year"]) for r in daily})
        rows.append(
            {
                "source": "Daymet V4 R1 (1 km)",
                "detail": f"{years[0]}-{years[-1]}",
                **annual_mean_days_tmax_ge(daily, THRESHOLDS),
            }
        )
    except Exception as exc:  # e.g. Daymet not yet updated for the latest year
        rows.append({"source": "Daymet V4 R1 (1 km)", "detail": f"unavailable: {exc}"[:28]})

    # Long-term reference: what the 1991-2020 normal period looked like at the same point.
    rows.append(
        _acis_grid_row(loc, settings, http, settings.acis.grid, *REFERENCE)
        | {"source": "REFERENCE ACIS grid 21 (PRISM)"}
    )
    ref = fetch_normals(http, settings, loc, ["ANN-TMAX-AVGNDS-GRTH090", "ANN-TMAX-AVGNDS-GRTH100"])
    n90, n100 = ref["ANN-TMAX-AVGNDS-GRTH090"], ref["ANN-TMAX-AVGNDS-GRTH100"]
    rows.append(
        {
            "source": "REFERENCE NOAA Normals (station)",
            "detail": (
                f"1991-2020 {n90.station.id} {n90.station.distance_km:.0f}km"
                if n90.station
                else n90.note
            ),
            90: n90.value,
            100: n100.value,
            105: None,
        }
    )
    return rows
