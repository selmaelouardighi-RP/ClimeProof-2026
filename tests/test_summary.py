import json

from typer.testing import CliRunner

from climeproof.catalog import METRICS_BY_ID
from climeproof.cli import app
from climeproof.pipeline import run, write_outputs
from climeproof.providers.base import PointProvider
from climeproof.schema import Location, Provenance, StationRef, Status
from climeproof.summary import round_for_display, summarize

from .conftest import FIXED_TIME, FakeHttp

LOC = Location(id="query", latitude=47.4447, longitude=-122.3144)
STATION = StationRef(
    id="USW00024233",
    name="SEATTLE TACOMA AIRPORT",
    latitude=47.44,
    longitude=-122.31,
    elevation_m=112.5,
    distance_km=0.04,
)


def _prov(dataset, station=None):
    return Provenance(
        source="ACIS",
        dataset=dataset,
        dataset_version="1",
        retrieved_at=FIXED_TIME,
        request="POST https://example/very/long/request",
        response_sha256="abc",
        method="m",
        station=station,
    )


class Grid(PointProvider):
    name = "acis_grid"

    def run_point(self, loc):
        out = {
            mid: self.ok(mid, 4.533333, _prov("GridData"), "2011-2025") for mid in self.metric_ids
        }
        out["heat.heatwave_events_per_year"] = self.missing(Status.NO_DATA, "no grid here")
        return out


class Station(PointProvider):
    name = "acis_station"

    def run_point(self, loc):
        p = _prov("StnData", STATION)
        return {
            "heat.record_high_f": self.ok(
                "heat.record_high_f", 108.0, p, "por", "observed on 2021-06-28"
            ),
            "cold.record_low_f": self.ok(
                "cold.record_low_f", -0.0, p, "por", "observed on 1950-01-31"
            ),
        }


class Broken(PointProvider):
    name = "acis_snow"

    def run_point(self, loc):
        raise RuntimeError("boom")


REGISTRY = {"acis_grid": Grid, "acis_station": Station, "acis_snow": Broken}


def _records(settings, locs=(LOC,)):
    return run(list(locs), settings, FakeHttp(lambda *a: {}), registry=REGISTRY)


def test_rounding():
    assert round_for_display(4.533333) == 4.5
    assert round_for_display(108.0) == 108 and isinstance(round_for_display(108.0), int)
    assert round_for_display(0.066667) == 0.067
    assert round_for_display(2e-05) == 2e-05
    assert round_for_display(-0.0) == 0 and json.dumps(round_for_display(-0.0)) == "0"
    assert round_for_display("text") == "text"


def test_summary_shape(settings):
    s = summarize(_records(settings)[0])
    assert s["location"] == {"latitude": 47.4447, "longitude": -122.3144}  # no "query" id, no nulls
    assert s["periods"] == {
        "recent": "2011-2025",
        "trend": "1996-2025",
        "records_through": "2026-10-15",
    }
    assert s["sources"] == {
        "acis_grid": {"name": "ACIS", "dataset": "GridData"},
        "acis_station": {"name": "ACIS", "dataset": "StnData"},
    }
    heat = s["hazards"]["heat"]
    assert heat["days_ge_100f"] == {
        "label": METRICS_BY_ID["heat.days_ge_100f"].description,
        "value": 4.5,
        "unit": "days/yr",
        "period": "2011-2025",
        "source": "acis_grid",
    }
    assert heat["record_high_f"]["observed"] == "2021-06-28"
    assert heat["record_high_f"]["station"] == {
        "name": "SEATTLE TACOMA AIRPORT",
        "id": "USW00024233",
        "distance_km": 0.0,
    }
    # gaps stay visible, failures stay visible; neither carries a value or source
    assert heat["heatwave_events_per_year"] == {
        "label": heat["heatwave_events_per_year"]["label"],
        "status": "NO_DATA",
        "note": "no grid here",
    }
    snow = s["hazards"]["winter_storm"]["annual_snowfall_in"]
    assert snow["status"] == "ERROR" and "boom" in snow["note"] and "value" not in snow


def test_summary_drops_not_implemented_and_audit_fields(settings):
    s = summarize(_records(settings)[0])
    assert "flood" not in s["hazards"]  # all NOT_IMPLEMENTED
    text = json.dumps(s)
    for audit in (
        "request",
        "response_sha256",
        "retrieved_at",
        "NOT_IMPLEMENTED",
        "config_sha256",
        "-0.0",
    ):
        assert audit not in text


def test_batch_writes_summary_jsonl(settings, tmp_path):
    locs = [Location(id="a", latitude=35.0, longitude=-100.0, county_fips="40001")]
    paths = write_outputs(_records(settings, locs), tmp_path)
    [line] = paths["summary"].read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["location"] == {
        "id": "a",
        "latitude": 35.0,
        "longitude": -100.0,
        "county_fips": "40001",
    }


def test_summarize_command_matches_in_run_summary(settings, tmp_path):
    record = _records(settings)[0]
    full = tmp_path / "rec.json"
    full.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    out = tmp_path / "summary.json"
    result = CliRunner().invoke(app, ["summarize", str(full), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8")) == summarize(record)
