"""Output record schema.

Every location gets a record holding EVERY metric in the catalog (see catalog.py), each with
a status. The statuses keep apart the cases the work scope says must stay distinct:

- OK               value present, provenance attached
- N/A              hazard does not apply at this location (e.g. storm surge inland)
- NO_DATA          hazard could apply, but no public dataset covers this location
- NOT_IMPLEMENTED  the pipeline does not compute this metric yet (dev-time only; zero at handoff)
- ERROR            a source failed for this location; `note` says why. Rerun, don't interpret.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator

SCHEMA_VERSION = "0.2.0"  # 0.2: metrics computed over a recent rolling window


class Status(StrEnum):
    OK = "OK"
    NOT_APPLICABLE = "N/A"
    NO_DATA = "NO_DATA"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    ERROR = "ERROR"


class StationRef(BaseModel):
    id: str
    name: str | None = None
    latitude: float
    longitude: float
    elevation_m: float | None = None
    distance_km: float


class GridCellRef(BaseModel):
    latitude: float
    longitude: float
    elevation_m: float | None = None


class Provenance(BaseModel):
    source: str  # organisation / product, e.g. "NOAA NCEI U.S. Climate Normals"
    dataset: str  # dataset identifier, e.g. "ACIS GridData grid 21 (PRISM)"
    dataset_version: str
    retrieved_at: datetime  # when the raw response was fetched (from the cache entry)
    request: str  # canonical request (URL + params) that produced the raw response
    response_sha256: str | None = None  # hash of the raw response body, for auditing
    method: str  # how the value was derived from the raw response
    station: StationRef | None = None
    grid_cell: GridCellRef | None = None


class MetricValue(BaseModel):
    status: Status
    value: float | str | None = None
    unit: str | None = None
    period: str | None = None
    provenance: Provenance | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> MetricValue:
        if self.status is Status.OK:
            if self.value is None:
                raise ValueError("status OK requires a value")
            if self.provenance is None:
                raise ValueError("status OK requires provenance")
        elif self.value is not None:
            raise ValueError(f"status {self.status} must not carry a value")
        return self


class Location(BaseModel):
    id: str
    latitude: float
    longitude: float
    input_address: str | None = None
    matched_address: str | None = None
    state_fips: str | None = None
    county_fips: str | None = None  # 5-digit state+county GEOID
    geocode_provenance: Provenance | None = None


class RunInfo(BaseModel):
    pipeline_version: str
    schema_version: str = SCHEMA_VERSION
    config_version: str
    config_sha256: str
    generated_at: datetime
    # The data windows this run used (they roll forward with the calendar).
    recent_period: str  # e.g. "2011-2025": climate statistics
    trend_period: str  # e.g. "1996-2025": trends
    records_through: str  # last date included in period-of-record extremes


class HazardRecord(BaseModel):
    run: RunInfo
    location: Location
    metrics: dict[str, MetricValue]  # keyed by catalog metric id, e.g. "heat.days_ge_100f"
