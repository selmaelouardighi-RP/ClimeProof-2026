"""Bulk input loading. Accepted CSV shapes (header row required, `id` always required):

  id, latitude, longitude                 -> used as-is (no geocoding)
  id, street, city, state, zip            -> Census batch geocoder
  id, address                             -> Census one-line geocoder, row by row

Rows may mix shapes; each row uses the first shape it satisfies.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .config import Settings
from .geocode import GeocodeError, geocode_batch, geocode_one
from .http import CachedHttp
from .schema import Location

log = logging.getLogger(__name__)


def read_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = [
            {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            for r in csv.DictReader(f)
        ]
    ids = [r.get("id", "") for r in rows]
    if any(not i for i in ids):
        raise ValueError("every input row needs a non-empty `id`")
    if len(set(ids)) != len(ids):
        raise ValueError("input `id` values must be unique")
    return rows


def build_locations(
    rows: list[dict[str, str]], settings: Settings, http: CachedHttp
) -> tuple[list[Location], dict[str, str]]:
    """Return (locations in input order, {id: reason} for rows that could not be placed)."""
    placed: dict[str, Location] = {}
    failures: dict[str, str] = {}
    batch, oneline = [], []
    for r in rows:
        if r.get("latitude") and r.get("longitude"):
            placed[r["id"]] = Location(
                id=r["id"], latitude=float(r["latitude"]), longitude=float(r["longitude"])
            )
        elif r.get("street"):
            batch.append(r)
        elif r.get("address"):
            oneline.append(r)
        else:
            failures[r["id"]] = "row has neither coordinates nor an address"

    if batch:
        locs, fails = geocode_batch(http, settings.geocoder, batch)
        placed.update({loc.id: loc for loc in locs})
        failures.update(fails)
    for r in oneline:
        try:
            placed[r["id"]] = geocode_one(http, settings.geocoder, r["id"], r["address"])
        except GeocodeError as exc:
            failures[r["id"]] = str(exc)

    for rid, why in failures.items():
        log.warning("could not place %s: %s", rid, why)
    return [placed[r["id"]] for r in rows if r["id"] in placed], failures
