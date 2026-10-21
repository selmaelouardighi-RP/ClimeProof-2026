"""Applied Climate Information System (ACIS) web services.

- GridData: point extraction from a daily gridded product (grid 21 = PRISM, updated daily)
  with server-side reductions such as "count of days with Tmax >= 100F per year".
- StnMeta / StnData: GHCN-Daily-based station metadata, annual summaries and period-of-record
  extremes.

All climate statistics use the RECENT window from config (`periods.recent_start..recent_end`,
the most recent complete calendar years); the trend uses the longer `trend_start..recent_end`.

Docs: https://www.rcc-acis.org/docs_webservices.html
Values come back in degF / inches. Missing values: -999 (grids), "M" (stations).
"""

from __future__ import annotations

from collections.abc import Callable

from ..climate_stats import count_runs, mean_with_coverage, percentile, trend_per_decade
from ..geo import bbox_around, haversine_km
from ..schema import GridCellRef, Location, MetricValue, Provenance, StationRef, Status
from .base import PointProvider

SOURCE = "acis"
FT_TO_M = 0.3048
GRID_NAMES = {"1": "NRCC Interpolated", "3": "NRCC Hi-Res", "21": "PRISM"}
# Grid cells are ~4-5 km; a returned cell farther than this means the point is off-grid.
MAX_GRID_CELL_OFFSET_KM = 10.0


def grid_cell_offset_km(loc: Location, cell: GridCellRef) -> float | None:
    if cell.latitude != cell.latitude or cell.longitude != cell.longitude:  # NaN: no meta
        return None
    return haversine_km(loc.latitude, loc.longitude, cell.latitude, cell.longitude)


def num(v) -> float | None:
    """Parse an ACIS value; None for missing. Trace ("T") counts as 0."""
    if v is None:
        return None
    if isinstance(v, list):  # value with appended flags/dates: [value, ...]
        v = v[0]
    if isinstance(v, str):
        v = v.strip().rstrip("ASE")  # strip ACIS flags (accumulated/subsequent/estimated)
        if v in ("M", ""):
            return None
        if v == "T":
            return 0.0
    f = float(v)
    return None if f <= -999 else f


def _check(payload: dict) -> dict:
    if "error" in payload:
        raise RuntimeError(f"ACIS error: {payload['error']}")
    return payload


def _yly(elem: str, reduce: str, **extra) -> dict:
    return {"name": elem, "interval": "yly", "duration": "yly", "reduce": reduce, **extra}


class AcisGridProvider(PointProvider):
    """Recent-years gridded statistics at the exact point (no station-distance problem)."""

    name = "acis_grid"

    # (metric id, element, reduction) for the annual-reduction request, in response order.
    ANNUAL = [
        ("heat.days_ge_90f", "maxt", "cnt_ge_90"),
        ("heat.days_ge_100f", "maxt", "cnt_ge_100"),
        ("heat.days_ge_105f", "maxt", "cnt_ge_105"),
        ("heat.cooling_degree_days", "cdd", "sum"),
        ("cold.freeze_days", "mint", "cnt_le_32"),
        ("cold.hard_freeze_days", "mint", "cnt_le_28"),
        ("cold.days_tmin_le_0f", "mint", "cnt_le_0"),
        ("cold.heating_degree_days", "hdd", "sum"),
        ("extreme_precip.annual_precip_in", "pcpn", "sum"),
        ("extreme_precip.days_ge_1in", "pcpn", "cnt_ge_1.00"),
        ("extreme_precip.mean_annual_max_1day_in", "pcpn", "max"),
    ]

    def run_point(self, loc: Location) -> dict[str, MetricValue]:
        cfg, per = self.settings.acis, self.settings.periods
        grid_label = f"ACIS GridData grid {cfg.grid} ({GRID_NAMES.get(cfg.grid, 'unknown')})"
        loc_str = f"{loc.longitude:.5f},{loc.latitude:.5f}"
        out: dict[str, MetricValue] = {}

        # 1) annual reductions over the recent window, one row per year
        resp = self._grid(
            loc_str,
            str(per.recent_start),
            str(per.recent_end),
            [_yly(e, r) for _, e, r in self.ANNUAL],
            meta="ll,elev",
        )
        d = _check(resp.json())
        cell = grid_cell_ref(d.get("meta", {}))
        # Outside a grid's domain (e.g. PRISM for HI/AK) ACIS silently returns some other cell.
        offset_km = grid_cell_offset_km(loc, cell)
        if offset_km is None or offset_km > MAX_GRID_CELL_OFFSET_KM:
            away = (
                "no cell returned" if offset_km is None else f"nearest cell {offset_km:.0f} km away"
            )
            return self.all_with(Status.NO_DATA, f"point outside {grid_label} domain ({away})")
        cols = list(zip(*[row[1:] for row in d["data"]], strict=True))

        def prov(method: str, r) -> Provenance:
            return Provenance(
                source="ACIS (RCC-ACIS)",
                dataset=grid_label,
                dataset_version=f"grid={cfg.grid}",
                retrieved_at=r.retrieved_at,
                request=r.request,
                response_sha256=r.sha256,
                method=method,
                grid_cell=cell,
            )

        for i, (mid, elem, red) in enumerate(self.ANNUAL):
            mean = mean_with_coverage([num(v) for v in cols[i]], per.min_year_coverage)
            out[mid] = (
                self.ok(
                    mid,
                    mean,
                    prov(f"mean over years of annual {elem} {red}", resp),
                    per.recent_label,
                )
                if mean is not None
                else self.missing(Status.NO_DATA, f"insufficient valid years in {per.recent_label}")
            )

        # 2) trend of >= 100F days over the longer trend window
        tid = "heat.days_ge_100f_trend"
        tresp = self._grid(
            loc_str, str(per.trend_start), str(per.recent_end), [_yly("maxt", "cnt_ge_100")]
        )
        rows = _check(tresp.json())["data"]
        slope = trend_per_decade(
            [int(r[0]) for r in rows], [num(r[1]) for r in rows], per.min_year_coverage
        )
        out[tid] = (
            self.ok(
                tid, slope, prov("OLS slope x10 of annual maxt cnt_ge_100", tresp), per.trend_label
            )
            if slope is not None
            else self.missing(Status.NO_DATA, f"insufficient valid years in {per.trend_label}")
        )

        # 3) daily Tmax over the recent window for heat-wave events
        out["heat.heatwave_events_per_year"] = self._heatwaves(loc_str, prov)
        return out

    def _grid(self, loc_str: str, sdate: str, edate: str, elems: list, meta: str | None = None):
        cfg = self.settings.acis
        payload = {"loc": loc_str, "grid": cfg.grid, "sdate": sdate, "edate": edate, "elems": elems}
        if meta:
            payload["meta"] = meta
        return self.http.post_json(SOURCE, f"{cfg.base_url}/GridData", payload)

    def _heatwaves(self, loc_str: str, prov: Callable[..., Provenance]) -> MetricValue:
        per, hw = self.settings.periods, self.settings.heatwave
        resp = self._grid(
            loc_str, f"{per.recent_start}-01-01", f"{per.recent_end}-12-31", [{"name": "maxt"}]
        )
        tmax = [num(v) for _, v in _check(resp.json())["data"]]
        valid = [t for t in tmax if t is not None]
        if not tmax or len(valid) / len(tmax) < per.min_year_coverage:
            return self.missing(Status.NO_DATA, "insufficient valid days in daily Tmax series")
        thr = percentile(valid, hw.tmax_percentile)
        events = count_runs(
            [None if t is None else t >= thr for t in tmax], hw.min_consecutive_days
        )
        n_years = per.n_recent_years
        method = (
            f"events of >= {hw.min_consecutive_days} consecutive days with Tmax >= "
            f"p{hw.tmax_percentile} of daily Tmax {per.recent_label} ({thr:.1f}F); "
            f"events / {n_years} yr"
        )
        return self.ok(
            "heat.heatwave_events_per_year",
            events / n_years,
            prov(method, resp),
            per.recent_label,
            note="PROVISIONAL heat-wave definition; pending data/science sign-off",
        )


# --- stations ---------------------------------------------------------------------------------
RangeTest = Callable[[int, int], bool]  # (first year, last year) of an element's record -> ok?


def _station_meta(provider: PointProvider, loc: Location, elems: str) -> list[dict]:
    cfg = provider.settings.acis
    w, s, e, n = bbox_around(loc.latitude, loc.longitude, cfg.station_search_km)
    resp = provider.http.post_json(
        SOURCE,
        f"{cfg.base_url}/StnMeta",
        {
            "bbox": f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}",
            "elems": elems,
            "meta": "name,sids,ll,elev,valid_daterange",
        },
    )
    return _check(resp.json()).get("meta", [])


def nearest_stations(
    loc: Location, metas: list[dict], max_km: float, test: RangeTest, require_all: bool
) -> list[StationRef]:
    """Stations within max_km whose element records pass `test` (all elements, or any),
    nearest first."""
    out: list[StationRef] = []
    for m in metas:
        if "ll" not in m or not m.get("sids"):
            continue
        ranges = m.get("valid_daterange") or []
        oks = [bool(r) and test(int(r[0][:4]), int(r[1][:4])) for r in ranges]
        if not oks or not (all(oks) if require_all else any(oks)):
            continue
        lon, lat = m["ll"]
        dist = haversine_km(loc.latitude, loc.longitude, lat, lon)
        if dist <= max_km:
            out.append(
                StationRef(
                    id=_preferred_sid(m["sids"]),
                    name=m.get("name"),
                    latitude=lat,
                    longitude=lon,
                    distance_km=round(dist, 2),
                    elevation_m=round(m["elev"] * FT_TO_M, 1)
                    if m.get("elev") is not None
                    else None,
                )
            )
    return sorted(out, key=lambda s: (s.distance_km, s.id))


class AcisStationProvider(PointProvider):
    """Record highs / lows to date, from the nearest active station with a long record."""

    name = "acis_station"

    def run_point(self, loc: Location) -> dict[str, MetricValue]:
        cfg, per = self.settings.acis, self.settings.periods

        def long_and_active(first: int, last: int) -> bool:
            return last - first >= cfg.min_record_years and last >= per.recent_end

        stations = nearest_stations(
            loc,
            _station_meta(self, loc, "maxt,mint"),
            cfg.max_station_distance_km,
            long_and_active,
            require_all=True,
        )
        if not stations:
            return self.all_with(
                Status.NO_DATA,
                (
                    f"no station within {cfg.max_station_distance_km:g} km with >= "
                    f"{cfg.min_record_years} yr of Tmax and Tmin, reporting in {per.recent_end}"
                ),
            )
        station = stations[0]

        smry_elem = {"interval": "dly", "duration": "dly", "smry_only": 1}
        resp = self.http.post_json(
            SOURCE,
            f"{cfg.base_url}/StnData",
            {
                "sid": station.id,
                "sdate": "por",
                "edate": per.records_end,
                "meta": "name,ll",
                "elems": [
                    {"name": "maxt", "smry": {"reduce": "max", "add": "date"}, **smry_elem},
                    {"name": "mint", "smry": {"reduce": "min", "add": "date"}, **smry_elem},
                ],
            },
        )
        smry = _check(resp.json()).get("smry", [])
        out: dict[str, MetricValue] = {}
        for i, (mid, word) in enumerate(
            [
                ("heat.record_high_f", "highest daily Tmax"),
                ("cold.record_low_f", "lowest daily Tmin"),
            ]
        ):
            val = num(smry[i]) if i < len(smry) else None
            when = smry[i][1] if i < len(smry) and len(smry[i]) > 1 else None
            if val is None:
                out[mid] = self.missing(Status.NO_DATA, "station summary missing")
                continue
            prov = Provenance(
                source="ACIS (RCC-ACIS), GHCN-Daily station data",
                dataset="ACIS StnData",
                dataset_version=f"period of record through {per.records_end}",
                retrieved_at=resp.retrieved_at,
                request=resp.request,
                response_sha256=resp.sha256,
                method=f"{word} in station period of record",
                station=station,
            )
            out[mid] = self.ok(mid, val, prov, f"por-{per.records_end}", note=f"observed on {when}")
        return out


class AcisSnowProvider(PointProvider):
    """Recent-years snowfall and snow-cover days from the nearest station with a complete record.

    Gridded PRISM has no snow, so this is station-based. One MultiStnData request returns the
    recent annual series of EVERY station in the search box; each metric then takes the nearest
    station whose series meets the coverage rule (many volunteer stations report patchily).
    """

    name = "acis_snow"

    ELEMS = [
        ("winter_storm.annual_snowfall_in", "snow", "sum"),
        ("winter_storm.days_snow_depth_ge_1in", "snwd", "cnt_ge_1"),
    ]

    def run_point(self, loc: Location) -> dict[str, MetricValue]:
        cfg, per = self.settings.acis, self.settings.periods
        w, s, e, n = bbox_around(loc.latitude, loc.longitude, cfg.station_search_km)
        resp = self.http.post_json(
            SOURCE,
            f"{cfg.base_url}/MultiStnData",
            {
                "bbox": f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}",
                "meta": "name,sids,ll,elev",
                "sdate": str(per.recent_start),
                "edate": str(per.recent_end),
                "elems": [
                    _yly(el, r, maxmissing=cfg.max_missing_days_per_year) for _, el, r in self.ELEMS
                ],
            },
        )
        # (station, [mean or None per metric]) for stations inside the radius, nearest first
        scored: list[tuple[StationRef, list[float | None]]] = []
        for st in _check(resp.json()).get("data", []):
            m = st.get("meta", {})
            if "ll" not in m or not m.get("sids"):
                continue
            lon, lat = m["ll"]
            dist = haversine_km(loc.latitude, loc.longitude, lat, lon)
            if dist > cfg.max_station_distance_km:
                continue
            rows = st.get("data", [])
            means = [
                mean_with_coverage([num(r[i]) for r in rows], per.min_year_coverage)
                if len(rows) == per.n_recent_years
                else None
                for i in range(len(self.ELEMS))
            ]
            ref = StationRef(
                id=_preferred_sid(m["sids"]),
                name=m.get("name"),
                latitude=lat,
                longitude=lon,
                distance_km=round(dist, 2),
                elevation_m=round(m["elev"] * FT_TO_M, 1) if m.get("elev") is not None else None,
            )
            scored.append((ref, means))
        scored.sort(key=lambda x: (x[0].distance_km, x[0].id))

        out: dict[str, MetricValue] = {}
        for i, (mid, elem, red) in enumerate(self.ELEMS):
            hit = next(((ref, ms[i]) for ref, ms in scored if ms[i] is not None), None)
            if hit is None:
                out[mid] = self.missing(
                    Status.NO_DATA,
                    (
                        f"none of {len(scored)} stations within {cfg.max_station_distance_km:g} km "
                        f"has a complete {per.recent_label} {elem} record"
                    ),
                )
                continue
            ref, mean = hit
            prov = Provenance(
                source="ACIS (RCC-ACIS), GHCN-Daily station data",
                dataset="ACIS MultiStnData",
                dataset_version=(
                    f"annual {elem} {red}, <= {cfg.max_missing_days_per_year} missing days/yr"
                ),
                retrieved_at=resp.retrieved_at,
                request=resp.request,
                response_sha256=resp.sha256,
                method=(
                    f"mean over years of annual {elem} {red} at the nearest station with "
                    f">= {per.min_year_coverage:.0%} complete years"
                ),
                station=ref,
            )
            out[mid] = self.ok(mid, mean, prov, per.recent_label)
        return out


def _preferred_sid(sids: list[str]) -> str:
    """Prefer the GHCN-Daily id (ACIS sid type 6); fall back to the first id."""
    for sid in sids:
        ident, _, kind = sid.rpartition(" ")
        if kind == "6":
            return ident
    return sids[0].rpartition(" ")[0] or sids[0]


def grid_cell_ref(meta: dict) -> GridCellRef:
    elev = meta.get("elev")
    return GridCellRef(
        latitude=meta.get("lat", float("nan")),
        longitude=meta.get("lon", float("nan")),
        elevation_m=round(elev * FT_TO_M, 1) if elev is not None else None,
    )
