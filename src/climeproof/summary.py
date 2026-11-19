"""Client summary: a short, readable view of a full HazardRecord.

The full record (records.jsonl / profile JSON) stays the canonical, auditable output. The
summary is derived from it and adds nothing, so the two can never disagree:

- NOT_IMPLEMENTED metrics are dropped (development-only).
- NO_DATA / N/A / ERROR metrics are kept, with `status` and `note`, so a gap is never hidden.
- Provenance is reduced to a source key (listed once under `sources`) and, for station-based
  metrics, the station's name, id and distance. Requests, hashes and retrieval times stay in
  the full record.
- Values are rounded for reading: 1 decimal at or above 1, else 2 significant figures.
"""

from __future__ import annotations

import re
from typing import Any

from .catalog import METRICS_BY_ID
from .schema import HazardRecord, MetricValue, Status

SUMMARY_VERSION = "1"  # bump when the summary's shape changes
SINGLE_POINT_ID = "query"  # id the CLI gives a one-off `profile` location; not shown
_OBSERVED = re.compile(r"^observed on (\S+)$")


def round_for_display(value: float | str) -> float | int | str:
    if isinstance(value, str):
        return value
    if value == 0:  # also catches -0.0
        return 0
    value = round(value, 1) if abs(value) >= 1 else float(f"{value:.2g}")
    return int(value) if value.is_integer() else value


def summarize(record: HazardRecord) -> dict[str, Any]:
    sources: dict[str, dict[str, str]] = {}
    hazards: dict[str, dict[str, Any]] = {}

    for mid, mv in record.metrics.items():
        if mv.status is Status.NOT_IMPLEMENTED:
            continue
        metric = METRICS_BY_ID[mid]
        ok = mv.status is Status.OK  # OK always has provenance; only OK values cite a source
        source = _source_key(sources, metric.provider or "source", mv) if ok else None
        entry = _metric_entry(mv, metric.description, source)
        hazards.setdefault(metric.hazard, {})[mid.split(".", 1)[1]] = entry

    loc = record.location
    location: dict[str, Any] = {"latitude": loc.latitude, "longitude": loc.longitude}
    if loc.id != SINGLE_POINT_ID:
        location = {"id": loc.id, **location}
    if address := loc.matched_address or loc.input_address:
        location["address"] = address
    if loc.county_fips:
        location["county_fips"] = loc.county_fips

    run = record.run
    return {
        "summary_version": SUMMARY_VERSION,
        "schema_version": run.schema_version,
        "generated_at": run.generated_at.isoformat().replace("+00:00", "Z"),
        "location": location,
        "periods": {
            "recent": run.recent_period,
            "trend": run.trend_period,
            "records_through": run.records_through,
        },
        "sources": sources,
        "hazards": hazards,
    }


def _metric_entry(mv: MetricValue, label: str, source: str | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"label": label}
    if mv.status is not Status.OK:
        entry["status"] = mv.status.value
        if mv.note:
            entry["note"] = mv.note
        return entry

    entry["value"] = round_for_display(mv.value)
    for key in ("unit", "period"):
        if (v := getattr(mv, key)) is not None:
            entry[key] = v
    if mv.note:
        m = _OBSERVED.match(mv.note)
        entry["observed" if m else "note"] = m.group(1) if m else mv.note
    if source:
        entry["source"] = source
    station = mv.provenance.station if mv.provenance else None
    if station is not None:
        entry["station"] = {
            k: v
            for k, v in (
                ("name", station.name),
                ("id", station.id),
                ("distance_km", round(station.distance_km, 1)),
            )
            if v is not None
        }
    return entry


def _source_key(sources: dict[str, dict[str, str]], base: str, mv: MetricValue) -> str:
    """Key into `sources`; one entry per distinct (source, dataset)."""
    desc = {"name": mv.provenance.source, "dataset": mv.provenance.dataset}
    key, n = base, 1
    while key in sources and sources[key] != desc:
        n += 1
        key = f"{base}_{n}"
    sources[key] = desc
    return key
