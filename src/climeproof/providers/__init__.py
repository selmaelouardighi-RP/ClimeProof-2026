"""Provider registry: catalog `Metric.provider` names -> implementation classes."""

from __future__ import annotations

from .acis import AcisGridProvider, AcisSnowProvider, AcisStationProvider
from .base import PointProvider, Provider, Results
from .open_climate_risk import OpenClimateRiskProvider

REGISTRY: dict[str, type[Provider]] = {
    cls.name: cls
    for cls in (AcisGridProvider, AcisStationProvider, AcisSnowProvider, OpenClimateRiskProvider)
}

__all__ = ["REGISTRY", "PointProvider", "Provider", "Results"]
