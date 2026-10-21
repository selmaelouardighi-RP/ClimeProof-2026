"""NOAA NCEI U.S. Climate Normals 1991-2020 (annual/seasonal product), station-based.

REFERENCE ONLY. Record fields describe the recent climate (see config `periods`) and are
computed from daily data; the 1991-2020 normals are the latest NOAA edition (the next, 2001-2030,
is due ~2031), so they are used by `climeproof compare` to show how far recent years have moved
from the long-term normal, not as a source for record fields.

Station discovery uses the NCEI Search Service (bbox query returns each station's location and
the data types it carries); values come from the NCEI Data Service.
  search: https://www.ncei.noaa.gov/access/services/search/v1/data
  data:   https://www.ncei.noaa.gov/access/services/data/v1
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import Settings
from ..geo import bbox_around, haversine_km
from ..http import CachedHttp
from ..schema import Location, StationRef

SOURCE = "ncei_normals"

TRACE = -7777.0  # NCEI special value: non-zero amount that rounds to zero


@dataclass(frozen=True)
class _Candidate:
    id: str
    name: str | None
    lat: float
    lon: float
    distance_km: float
    datatypes: frozenset[str]
    version: str


@dataclass(frozen=True)
class NormalValue:
    value: float | None
    station: StationRef | None
    note: str | None


def parse_value(raw: str | None) -> tuple[float | None, str | None]:
    """Return (value, note). NCEI special values (-9999, -8888, -6666, ...) -> None."""
    if raw is None or not str(raw).strip():
        return None, "value absent"
    v = float(raw)
    if v == TRACE:
        return 0.0, "trace (non-zero, rounds to 0)"
    if v <= -5555:
        return None, f"NCEI special value {v:g}"
    return v, None


def parse_candidates(search_json: dict, lat: float, lon: float) -> list[_Candidate]:
    out = []
    for r in search_json.get("results", []):
        try:
            sid = r["filePath"].rsplit("/", 1)[-1].removesuffix(".csv")
            slon, slat = r["boundingPoints"][0]["coordinates"]
        except (KeyError, IndexError, ValueError):
            continue
        stations = r.get("stations") or [{}]
        dts = frozenset(dt["id"] for st in stations for dt in st.get("dataTypes", []))
        m = re.search(r"_v(\d+\.\d+\.\d+)_", r.get("tar", ""))
        out.append(
            _Candidate(
                id=sid,
                name=stations[0].get("name"),
                lat=slat,
                lon=slon,
                distance_km=haversine_km(lat, lon, slat, slon),
                datatypes=dts,
                version=f"v{m.group(1)}" if m else "unknown",
            )
        )
    return sorted(out, key=lambda c: (c.distance_km, c.id))


def fetch_normals(
    http: CachedHttp, settings: Settings, loc: Location, datatypes: list[str]
) -> dict[str, NormalValue]:
    """Each data type from the NEAREST station that carries it (within the configured radius)."""
    cfg = settings.normals
    w, s, e, n = bbox_around(loc.latitude, loc.longitude, cfg.station_search_km)
    search = http.get(
        SOURCE,
        cfg.search_url,
        {
            "dataset": cfg.dataset,
            "bbox": f"{n:.4f},{w:.4f},{s:.4f},{e:.4f}",
            "limit": 1000,
        },
    )
    candidates = [
        c
        for c in parse_candidates(search.json(), loc.latitude, loc.longitude)
        if c.distance_km <= cfg.max_station_distance_km
    ]
    chosen = {dt: next((c for c in candidates if dt in c.datatypes), None) for dt in datatypes}
    ids = sorted({c.id for c in chosen.values() if c})
    rows: dict[str, dict] = {}
    if ids:
        data = http.get(
            SOURCE,
            cfg.data_url,
            {"dataset": cfg.dataset, "stations": ",".join(ids), "format": "json"},
        )
        rows = {r["STATION"]: r for r in data.json()}

    out: dict[str, NormalValue] = {}
    for dt, c in chosen.items():
        if c is None:
            out[dt] = NormalValue(None, None, f"no normals station with {dt} nearby")
            continue
        value, note = parse_value(rows.get(c.id, {}).get(dt))
        out[dt] = NormalValue(
            value,
            StationRef(
                id=c.id,
                name=c.name,
                latitude=c.lat,
                longitude=c.lon,
                distance_km=round(c.distance_km, 2),
            ),
            note,
        )
    return out
