import csv
import json

from climeproof.catalog import METRICS
from climeproof.pipeline import record_fingerprint, run, write_outputs
from climeproof.providers.base import PointProvider
from climeproof.schema import Location, Provenance, Status

from .conftest import FIXED_TIME, FakeHttp

LOCS = [
    Location(id="a", latitude=35.0, longitude=-100.0),
    Location(id="b", latitude=36.0, longitude=-101.0),
]


class GoodGrid(PointProvider):
    name = "acis_grid"

    def run_point(self, loc):
        prov = Provenance(
            source="test",
            dataset="test",
            dataset_version="1",
            retrieved_at=FIXED_TIME,
            request="test",
            method="test",
        )
        return {mid: self.ok(mid, loc.latitude, prov) for mid in self.metric_ids}


class BrokenForB(PointProvider):
    name = "acis_station"

    def run_point(self, loc):
        if loc.id == "b":
            raise RuntimeError("boom")
        return self.all_with(Status.NO_DATA, "nothing here")


REGISTRY = {"acis_grid": GoodGrid, "acis_station": BrokenForB}


def test_every_record_has_every_catalog_metric_in_order(settings):
    records = run(LOCS, settings, FakeHttp(lambda *a: {}), registry=REGISTRY)
    for r in records:
        assert list(r.metrics) == [m.id for m in METRICS]


def test_statuses(settings):
    a, b = run(LOCS, settings, FakeHttp(lambda *a: {}), registry=REGISTRY)
    assert a.metrics["heat.days_ge_90f"].status is Status.OK
    assert a.metrics["heat.record_high_f"].status is Status.NO_DATA
    assert b.metrics["heat.record_high_f"].status is Status.ERROR
    assert "boom" in b.metrics["heat.record_high_f"].note
    # provider not in this registry -> NOT_IMPLEMENTED, as are metrics with no provider at all
    assert a.metrics["winter_storm.annual_snowfall_in"].status is Status.NOT_IMPLEMENTED
    assert a.metrics["flood.likelihood_score"].status is Status.NOT_IMPLEMENTED


def test_reruns_are_identical_apart_from_timestamp(settings):
    r1 = run(LOCS, settings, FakeHttp(lambda *a: {}), registry=REGISTRY)
    r2 = run(LOCS, settings, FakeHttp(lambda *a: {}), registry=REGISTRY)
    assert [record_fingerprint(r) for r in r1] == [record_fingerprint(r) for r in r2]


def test_write_outputs(settings, tmp_path):
    records = run(LOCS, settings, FakeHttp(lambda *a: {}), registry=REGISTRY)
    paths = write_outputs(records, tmp_path / "out")
    lines = paths["jsonl"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["location"]["id"] == "a"
    with paths["long"].open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 2 * len(METRICS)
    with paths["wide"].open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["heat.days_ge_90f"] == "35.0"
    assert rows[1]["heat.record_high_f"] == "ERROR"


def test_records_state_the_data_windows_used(settings):
    run_info = run(LOCS, settings, FakeHttp(lambda *a: {}), registry=REGISTRY)[0].run
    assert (run_info.recent_period, run_info.trend_period, run_info.records_through) == (
        "2011-2025",
        "1996-2025",
        "2026-10-15",
    )
