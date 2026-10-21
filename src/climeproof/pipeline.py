"""Orchestration: locations -> providers -> complete, schema-conformant records -> files."""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .catalog import METRICS
from .config import Settings
from .http import CachedHttp
from .providers import REGISTRY, Provider
from .schema import SCHEMA_VERSION, HazardRecord, Location, MetricValue, RunInfo, Status

log = logging.getLogger(__name__)


def run(
    locations: list[Location],
    settings: Settings,
    http: CachedHttp,
    registry: dict[str, type[Provider]] | None = None,
) -> list[HazardRecord]:
    registry = REGISTRY if registry is None else registry
    results: dict[str, dict[str, MetricValue]] = {loc.id: {} for loc in locations}

    needed = sorted({m.provider for m in METRICS if m.provider})
    for name in needed:
        cls = registry.get(name)
        if cls is None:
            continue  # metrics fall through to NOT_IMPLEMENTED below
        provider = cls(settings, http)
        log.info("running provider %s on %d location(s)", name, len(locations))
        try:
            out = provider.run(locations)
        except Exception as exc:  # provider-wide failure (e.g. store unreachable)
            log.exception("provider %s failed", name)
            out = {
                loc.id: provider.all_with(Status.ERROR, f"{type(exc).__name__}: {exc}")
                for loc in locations
            }
        for loc_id, vals in out.items():
            results[loc_id].update({k: v for k, v in vals.items() if k in provider.metric_ids})

    run_info = RunInfo(
        pipeline_version=__version__,
        schema_version=SCHEMA_VERSION,
        config_version=settings.pipeline.config_version,
        config_sha256=settings.config_sha256,
        generated_at=datetime.now(UTC).replace(microsecond=0),
        recent_period=settings.periods.recent_label,
        trend_period=settings.periods.trend_label,
        records_through=settings.periods.records_end,
    )
    records = []
    for loc in locations:
        got = results[loc.id]
        metrics: dict[str, MetricValue] = {}
        for m in METRICS:  # catalog order -> identical field order in every record
            if m.id in got:
                metrics[m.id] = got[m.id]
            elif m.provider is None or m.provider not in registry:
                metrics[m.id] = MetricValue(status=Status.NOT_IMPLEMENTED)
            else:
                metrics[m.id] = MetricValue(
                    status=Status.ERROR, note=f"provider {m.provider} returned no value"
                )
        records.append(HazardRecord(run=run_info, location=loc, metrics=metrics))
    return records


# --- writers ------------------------------------------------------------------------------------
LONG_COLUMNS = [
    "location_id",
    "latitude",
    "longitude",
    "county_fips",
    "metric_id",
    "hazard",
    "status",
    "value",
    "unit",
    "period",
    "source",
    "dataset",
    "dataset_version",
    "station_id",
    "station_distance_km",
    "retrieved_at",
    "response_sha256",
    "method",
    "note",
]


def write_outputs(records: list[HazardRecord], out_dir: str | Path) -> dict[str, Path]:
    """records.jsonl (full, nested provenance) + metrics_long.csv (one row per location x metric)
    + metrics_wide.csv (one row per location, value columns only, for quick analysis)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "jsonl": out / "records.jsonl",
        "long": out / "metrics_long.csv",
        "wide": out / "metrics_wide.csv",
    }

    with paths["jsonl"].open("w", encoding="utf-8") as f:
        for r in records:
            f.write(r.model_dump_json() + "\n")

    with paths["long"].open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LONG_COLUMNS)
        w.writeheader()
        for r in records:
            for mid, mv in r.metrics.items():
                p = mv.provenance
                w.writerow(
                    {
                        "location_id": r.location.id,
                        "latitude": r.location.latitude,
                        "longitude": r.location.longitude,
                        "county_fips": r.location.county_fips,
                        "metric_id": mid,
                        "hazard": mid.split(".", 1)[0],
                        "status": mv.status.value,
                        "value": mv.value,
                        "unit": mv.unit,
                        "period": mv.period,
                        "source": p.source if p else None,
                        "dataset": p.dataset if p else None,
                        "dataset_version": p.dataset_version if p else None,
                        "station_id": p.station.id if p and p.station else None,
                        "station_distance_km": p.station.distance_km if p and p.station else None,
                        "retrieved_at": p.retrieved_at.isoformat() if p else None,
                        "response_sha256": p.response_sha256 if p else None,
                        "method": p.method if p else None,
                        "note": mv.note,
                    }
                )

    metric_ids = [m.id for m in METRICS]
    with paths["wide"].open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["location_id", "latitude", "longitude", "county_fips", *metric_ids])
        for r in records:
            w.writerow(
                [
                    r.location.id,
                    r.location.latitude,
                    r.location.longitude,
                    r.location.county_fips,
                    *[_wide_cell(r.metrics[mid]) for mid in metric_ids],
                ]
            )
    return paths


def _wide_cell(mv: MetricValue) -> str:
    return str(mv.value) if mv.status is Status.OK else mv.status.value


def record_fingerprint(record: HazardRecord) -> str:
    """Canonical JSON of a record minus run.generated_at - equal across deterministic reruns."""
    d = json.loads(record.model_dump_json())
    d["run"].pop("generated_at", None)
    return json.dumps(d, sort_keys=True)
