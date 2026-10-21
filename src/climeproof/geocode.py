"""Address -> coordinates + county via the U.S. Census Geocoder (public, no key, batch-capable).

Docs: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
"""

from __future__ import annotations

import csv
import io

from .config import GeocoderCfg
from .http import CachedHttp
from .schema import Location, Provenance

BASE = "https://geocoding.geo.census.gov/geocoder"
SOURCE = "census_geocoder"


class GeocodeError(RuntimeError):
    pass


def _provenance(cfg: GeocoderCfg, resp, method: str) -> Provenance:
    return Provenance(
        source="U.S. Census Bureau Geocoder",
        dataset=f"benchmark={cfg.benchmark}",
        dataset_version=f"vintage={cfg.vintage}",
        retrieved_at=resp.retrieved_at,
        request=resp.request,
        response_sha256=resp.sha256,
        method=method,
    )


def geocode_one(http: CachedHttp, cfg: GeocoderCfg, loc_id: str, address: str) -> Location:
    resp = http.get(
        SOURCE,
        f"{BASE}/geographies/onelineaddress",
        {
            "address": address,
            "benchmark": cfg.benchmark,
            "vintage": cfg.vintage,
            "layers": "Counties",
            "format": "json",
        },
    )
    matches = resp.json()["result"]["addressMatches"]
    if not matches:
        raise GeocodeError(f"{loc_id}: no Census match for address")
    m = matches[0]  # Census orders matches by score; first is the best match
    county = (m.get("geographies", {}).get("Counties") or [{}])[0]
    return Location(
        id=loc_id,
        latitude=float(m["coordinates"]["y"]),
        longitude=float(m["coordinates"]["x"]),
        input_address=address,
        matched_address=m.get("matchedAddress"),
        state_fips=county.get("STATE"),
        county_fips=county.get("GEOID"),
        geocode_provenance=_provenance(
            cfg, resp, f"onelineaddress; first of {len(matches)} match(es)"
        ),
    )


def geocode_batch(
    http: CachedHttp, cfg: GeocoderCfg, rows: list[dict[str, str]]
) -> tuple[list[Location], dict[str, str]]:
    """Geocode rows with id/street/city/state/zip. Returns (locations, {id: failure reason})."""
    locations: list[Location] = []
    failures: dict[str, str] = {}
    for start in range(0, len(rows), cfg.batch_size):
        chunk = rows[start : start + cfg.batch_size]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in chunk:
            w.writerow(
                [r["id"], r["street"], r.get("city", ""), r.get("state", ""), r.get("zip", "")]
            )
        resp = http.post_form(
            SOURCE,
            f"{BASE}/geographies/addressbatch",
            data={"benchmark": cfg.benchmark, "vintage": cfg.vintage},
            files={"addressFile": ("addresses.csv", buf.getvalue().encode(), "text/csv")},
        )
        by_id = {r["id"]: r for r in chunk}
        # Columns: id, input, match, match_type, matched_address, "lon,lat", tiger_id, side,
        #          state_fips, county_fips, tract, block
        for row in csv.reader(io.StringIO(resp.text)):
            if not row:
                continue
            rid = row[0]
            if len(row) < 6 or row[2] != "Match":
                failures[rid] = row[2] if len(row) > 2 else "unparseable response row"
                continue
            lon, lat = (float(v) for v in row[5].split(","))
            state = row[8] if len(row) > 8 else None
            county = row[9] if len(row) > 9 else None
            src = by_id.get(rid, {})
            locations.append(
                Location(
                    id=rid,
                    latitude=lat,
                    longitude=lon,
                    input_address=", ".join(
                        v
                        for v in (
                            src.get("street"),
                            src.get("city"),
                            src.get("state"),
                            src.get("zip"),
                        )
                        if v
                    ),
                    matched_address=row[4],
                    state_fips=state,
                    county_fips=(state + county) if state and county else None,
                    geocode_provenance=_provenance(cfg, resp, f"addressbatch; match type {row[3]}"),
                )
            )
    return locations, failures
