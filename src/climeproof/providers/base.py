"""Provider contract.

A provider owns one data source and computes a fixed set of catalog metrics for a batch of
locations. Two shapes cover everything so far:

- PointProvider: one independent query per location (REST APIs); run concurrently.
- Provider.run overridden directly: vectorised over all locations at once (gridded stores,
  where reading each chunk once for the whole batch is what makes bulk runs feasible).

A provider must return a MetricValue for every metric it owns, for every location. It reports
"no data here" as NO_DATA, never by omission; the pipeline turns omissions into ERRORs.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from ..catalog import METRICS_BY_ID, metrics_for_provider
from ..config import Settings
from ..http import CachedHttp
from ..schema import Location, MetricValue, Provenance, Status

log = logging.getLogger(__name__)

Results = dict[str, dict[str, MetricValue]]  # location id -> metric id -> value


class Provider(ABC):
    name: str

    def __init__(self, settings: Settings, http: CachedHttp) -> None:
        self.settings = settings
        self.http = http

    @property
    def metric_ids(self) -> list[str]:
        return [m.id for m in metrics_for_provider(self.name)]

    @abstractmethod
    def run(self, locations: list[Location]) -> Results: ...

    # --- helpers for building values ---------------------------------------------------------
    def all_with(self, status: Status, note: str) -> dict[str, MetricValue]:
        return {mid: MetricValue(status=status, note=note) for mid in self.metric_ids}

    @staticmethod
    def ok(
        metric_id: str,
        value: float | str,
        prov: Provenance,
        period: str | None = None,
        note: str | None = None,
    ) -> MetricValue:
        if isinstance(value, float):
            # + 0.0 turns -0.0 into 0.0 (e.g. ACIS "-0", or a tiny negative rounded to zero).
            value = round(value, 6) + 0.0
        return MetricValue(
            status=Status.OK,
            value=value,
            unit=METRICS_BY_ID[metric_id].unit,
            period=period,
            provenance=prov,
            note=note,
        )

    @staticmethod
    def missing(status: Status, note: str) -> MetricValue:
        return MetricValue(status=status, note=note)


class PointProvider(Provider):
    @abstractmethod
    def run_point(self, loc: Location) -> dict[str, MetricValue]: ...

    def run(self, locations: list[Location]) -> Results:
        def _safe(loc: Location) -> tuple[str, dict[str, MetricValue]]:
            try:
                return loc.id, self.run_point(loc)
            except Exception as exc:  # one bad location must not sink the batch
                log.warning("%s failed for %s: %s", self.name, loc.id, exc)
                return loc.id, self.all_with(Status.ERROR, f"{type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=max(1, self.settings.pipeline.workers)) as pool:
            return dict(pool.map(_safe, locations))
