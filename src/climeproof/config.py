"""Typed loader for config/pipeline.toml."""

from __future__ import annotations

import hashlib
import tomllib
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "pipeline.toml"


class PipelineCfg(BaseModel):
    config_version: str
    cache_dir: str
    user_agent: str
    workers: int = 4
    http_timeout_s: int = 120


class PeriodsCfg(BaseModel):
    recent_years: int = Field(ge=5)
    trend_years: int = Field(ge=10)
    end_year: int = 0  # 0 = last complete calendar year
    min_year_coverage: float = 0.9

    # Resolved once per run by resolve(); not read from the TOML.
    recent_start: int = 0
    recent_end: int = 0
    trend_start: int = 0
    records_end: str = ""

    def resolve(self, today: date) -> None:
        if self.end_year and self.end_year >= today.year:
            raise ValueError(f"periods.end_year={self.end_year} is not a complete year yet")
        end = self.end_year or today.year - 1
        self.recent_end = end
        self.recent_start = end - self.recent_years + 1
        self.trend_start = end - self.trend_years + 1
        # Pinned runs stop records at the pinned year; live runs include everything to date.
        self.records_end = (
            f"{end}-12-31" if self.end_year else (today - timedelta(days=1)).isoformat()
        )

    @property
    def recent_label(self) -> str:
        return f"{self.recent_start}-{self.recent_end}"

    @property
    def trend_label(self) -> str:
        return f"{self.trend_start}-{self.recent_end}"

    @property
    def n_recent_years(self) -> int:
        return self.recent_end - self.recent_start + 1


class HeatwaveCfg(BaseModel):
    min_consecutive_days: int
    tmax_percentile: int


class GeocoderCfg(BaseModel):
    benchmark: str
    vintage: str
    batch_size: int = 9000


class AcisCfg(BaseModel):
    base_url: str
    grid: str
    station_search_km: float
    max_station_distance_km: float
    min_record_years: int
    max_missing_days_per_year: int = 15


class NormalsCfg(BaseModel):
    dataset: str
    search_url: str
    data_url: str
    station_search_km: float
    max_station_distance_km: float


class DaymetCfg(BaseModel):
    url: str


class OpenClimateRiskCfg(BaseModel):
    bucket: str
    prefix: str
    region: str
    version: str
    snapshot_id: str = ""


class Settings(BaseModel):
    pipeline: PipelineCfg
    periods: PeriodsCfg
    heatwave: HeatwaveCfg
    geocoder: GeocoderCfg
    acis: AcisCfg
    normals: NormalsCfg
    daymet: DaymetCfg
    open_climate_risk: OpenClimateRiskCfg
    config_sha256: str = ""


def load_settings(path: str | Path | None = None, today: date | None = None) -> Settings:
    """Load config and resolve the rolling periods against `today` (default: the real date)."""
    p = Path(path) if path else DEFAULT_CONFIG
    raw = p.read_bytes()
    settings = Settings.model_validate(tomllib.loads(raw.decode("utf-8")))
    settings.config_sha256 = hashlib.sha256(raw).hexdigest()
    settings.periods.resolve(today or date.today())
    return settings
