"""CarbonPlan Open Climate Risk (OCR) - wildfire burn probability and structure risk, 30 m CONUS.

Store: Icechunk repository on Source Cooperative (anonymous S3), opened with xarray + zarr.
Docs:  https://docs.carbonplan.org/ocr/  (licence CC-BY-4.0)

Chunks are 6000 x 4500 cells, so a single point costs ~tens of seconds of transfer. The provider
therefore extracts ALL locations of a batch in one vectorised selection (each chunk read once)
and memoises each point's values in the response cache, keyed by snapshot + coordinates.
Requires the optional extra:  pip install -e ".[wildfire]"
"""

from __future__ import annotations

import json
import math

from ..geo import in_conus
from ..schema import GridCellRef, Location, MetricValue, Provenance, Status
from .base import Provider, Results

SOURCE = "open_climate_risk"

VARIABLES: dict[str, str] = {
    "wildfire.burn_probability_2011": "bp_2011",
    "wildfire.burn_probability_2047": "bp_2047",
    "wildfire.risk_to_potential_structures_2011": "rps_2011",
}


class OpenClimateRiskProvider(Provider):
    name = "open_climate_risk"

    def run(self, locations: list[Location]) -> Results:
        cfg = self.settings.open_climate_risk
        out: Results = {}
        todo: list[Location] = []
        for loc in locations:
            if in_conus(loc.latitude, loc.longitude):
                todo.append(loc)
            else:
                out[loc.id] = self.all_with(Status.NO_DATA, "Open Climate Risk covers CONUS only")
        if not todo:
            return out

        snapshot = cfg.snapshot_id or None
        cached, missing = {}, []
        if snapshot:  # point cache is only valid when the snapshot is pinned
            for loc in todo:
                hit = self.http.lookup(SOURCE, self._request(snapshot, loc))
                if hit:
                    cached[loc.id] = hit
                else:
                    missing.append(loc)
        else:
            missing = todo

        if missing:
            if self.http.offline:
                for loc in missing:
                    out[loc.id] = self.all_with(Status.ERROR, "offline and point not in cache")
                missing = []
            else:
                try:
                    cached.update(self._extract(missing))
                except ImportError as exc:
                    for loc in missing:
                        out[loc.id] = self.all_with(
                            Status.ERROR,
                            f"optional dependency missing ({exc}); install .[wildfire]",
                        )
                    missing = []

        for loc in todo:
            if loc.id in out:
                continue
            resp = cached[loc.id]
            body = json.loads(resp.text)
            cell = GridCellRef(latitude=body["cell_latitude"], longitude=body["cell_longitude"])
            vals: dict[str, MetricValue] = {}
            for mid, var in VARIABLES.items():
                v = body["values"].get(var)
                if v is None or math.isnan(v):
                    why = "non-burnable / water / outside domain"
                    vals[mid] = self.missing(Status.NO_DATA, f"{var} empty in 30 m cell ({why})")
                    continue
                prov = Provenance(
                    source="CarbonPlan Open Climate Risk",
                    dataset=f"s3://{cfg.bucket}/{cfg.prefix}",
                    dataset_version=f"{cfg.version} (icechunk snapshot {body['snapshot_id']})",
                    retrieved_at=resp.retrieved_at,
                    request=resp.request,
                    response_sha256=resp.sha256,
                    method=f"variable {var}, nearest 30 m cell",
                    grid_cell=cell,
                )
                vals[mid] = self.ok(mid, float(v), prov, "2011" if var.endswith("2011") else "2047")
            out[loc.id] = vals
        return out

    # ------------------------------------------------------------------------------------------
    def _request(self, snapshot: str, loc: Location) -> str:
        cfg = self.settings.open_climate_risk
        return (
            f"ICECHUNK s3://{cfg.bucket}/{cfg.prefix}@{snapshot} "
            f"vars={','.join(VARIABLES.values())} lat={loc.latitude:.6f} lon={loc.longitude:.6f}"
        )

    def _extract(self, locations: list[Location]):
        import icechunk
        import xarray as xr

        cfg = self.settings.open_climate_risk
        storage = icechunk.s3_storage(
            bucket=cfg.bucket, prefix=cfg.prefix, region=cfg.region, anonymous=True
        )
        repo = icechunk.Repository.open(storage)
        session = (
            repo.readonly_session(snapshot_id=cfg.snapshot_id)
            if cfg.snapshot_id
            else repo.readonly_session("main")
        )
        snapshot = session.snapshot_id
        ds = xr.open_dataset(session.store, engine="zarr", chunks=None)[list(VARIABLES.values())]
        pts = ds.sel(
            latitude=xr.DataArray([loc.latitude for loc in locations], dims="pt"),
            longitude=xr.DataArray([loc.longitude for loc in locations], dims="pt"),
            method="nearest",
        ).load()

        results = {}
        for i, loc in enumerate(locations):
            body = {
                "snapshot_id": snapshot,
                "cell_latitude": float(pts.latitude[i]),
                "cell_longitude": float(pts.longitude[i]),
                "values": {var: float(pts[var][i]) for var in VARIABLES.values()},
            }
            results[loc.id] = self.http.store(
                SOURCE, self._request(snapshot, loc), json.dumps(body, sort_keys=True)
            )
        return results
