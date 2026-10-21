import json
from datetime import date, timedelta

import pytest

from climeproof.providers.acis import (
    AcisGridProvider,
    AcisSnowProvider,
    AcisStationProvider,
    num,
)
from climeproof.providers.ncei_normals import fetch_normals, parse_value
from climeproof.providers.open_climate_risk import OpenClimateRiskProvider
from climeproof.schema import Location, Status

from .conftest import FakeHttp

LOC = Location(id="t", latitude=40.0, longitude=-100.0)
GRID_META = {"lat": 40.0, "lon": -100.0, "elev": 3000}


# --- ACIS ----------------------------------------------------------------------------------------
def test_acis_value_parsing():
    assert num(-999) is None and num("M") is None and num(None) is None
    assert num("T") == 0.0
    assert num("1.25A") == 1.25
    assert num(["122", "1990-06-26"]) == 122.0


def _daily_rows(start: date, end: date):
    """17 cool days then 3 hot days, repeating: every complete block is one 3-day heat wave."""
    pattern = [60.0] * 17 + [100.0] * 3
    n = (end - start).days + 1
    return [[str(start + timedelta(i)), pattern[i % 20]] for i in range(n)], n


def test_acis_grid_provider_uses_recent_window(settings):
    daily, n_days = _daily_rows(date(2011, 1, 1), date(2025, 12, 31))
    seen = {}

    def handler(method, url, payload):
        assert url.endswith("/GridData")
        elems = payload["elems"]
        if len(elems) == len(AcisGridProvider.ANNUAL):  # annual reductions, recent window
            seen["annual"] = (payload["sdate"], payload["edate"])
            rows = [
                [str(y), 10, y - 2011, 1, 900, 120, 100, 5, 6000, 30.0, 3, 2.5]
                for y in range(2011, 2026)
            ]
            rows[0][11] = -999  # one missing year of max 1-day precip is tolerated (14/15)
            return {"meta": GRID_META, "data": rows}
        if "reduce" in elems[0]:  # trend window
            seen["trend"] = (payload["sdate"], payload["edate"])
            return {"data": [[str(y), y - 1996] for y in range(1996, 2026)]}
        seen["daily"] = (payload["sdate"], payload["edate"])
        return {"data": daily}

    p = AcisGridProvider(settings, FakeHttp(handler))
    out = p.run_point(LOC)
    assert seen == {
        "annual": ("2011", "2025"),
        "trend": ("1996", "2025"),
        "daily": ("2011-01-01", "2025-12-31"),
    }
    assert set(out) == set(p.metric_ids)
    assert out["heat.days_ge_90f"].value == 10
    assert out["heat.days_ge_100f"].value == pytest.approx(7.0)
    assert out["heat.days_ge_100f"].period == "2011-2025"
    assert out["heat.days_ge_100f_trend"].value == pytest.approx(10.0)
    assert out["heat.days_ge_100f_trend"].period == "1996-2025"
    assert out["heat.cooling_degree_days"].value == 900
    assert out["cold.freeze_days"].value == 120
    assert out["cold.hard_freeze_days"].value == 100
    assert out["cold.days_tmin_le_0f"].value == 5
    assert out["cold.heating_degree_days"].value == 6000
    assert out["extreme_precip.annual_precip_in"].value == 30.0
    assert out["extreme_precip.days_ge_1in"].value == 3
    assert out["extreme_precip.mean_annual_max_1day_in"].value == 2.5
    assert out["heat.heatwave_events_per_year"].value == pytest.approx(
        (n_days // 20) / 15, abs=1e-6
    )
    assert out["heat.days_ge_100f"].provenance.grid_cell.elevation_m == pytest.approx(914.4)


def test_acis_grid_off_domain_point_is_no_data(settings):
    # Real ACIS behaviour: PRISM (grid 21) asked for Honolulu answers with a North Dakota cell.
    def handler(method, url, payload):
        return {"meta": {"lat": 47.166666, "lon": -99.333333, "elev": 1929}, "data": [["2011", 5]]}

    honolulu = Location(id="hi", latitude=21.3069, longitude=-157.8583)
    p = AcisGridProvider(settings, FakeHttp(handler))
    out = p.run_point(honolulu)
    assert set(out) == set(p.metric_ids)
    assert all(v.status is Status.NO_DATA for v in out.values())
    assert "outside" in out["cold.hard_freeze_days"].note


def test_acis_station_picks_nearest_long_record_active_station(settings):
    metas = [
        # closest, but record too short
        {
            "name": "SHORT",
            "sids": ["USC00000001 6"],
            "ll": [-100.01, 40.0],
            "elev": 100,
            "valid_daterange": [["2010-01-01", "2026-10-01"], ["2010-01-01", "2026-10-01"]],
        },
        # long record but closed before the recent window ends -> excluded
        {
            "name": "CLOSED",
            "sids": ["USC00000002 6"],
            "ll": [-100.02, 40.0],
            "elev": 100,
            "valid_daterange": [["1900-01-01", "2019-01-01"], ["1900-01-01", "2019-01-01"]],
        },
        {
            "name": "GOOD",
            "sids": ["123 2", "USW00000003 6"],
            "ll": [-100.1, 40.0],
            "elev": 100,
            "valid_daterange": [["1940-01-01", "2026-10-15"], ["1940-01-01", "2026-10-15"]],
        },
    ]

    def handler(method, url, payload):
        if url.endswith("/StnMeta"):
            return {"meta": metas}
        assert payload["sid"] == "USW00000003"
        assert payload["edate"] == "2026-10-15"  # records run through yesterday
        return {"meta": {}, "smry": [["108", "2024-07-14"], ["-31", "1989-12-22"]]}

    out = AcisStationProvider(settings, FakeHttp(handler)).run_point(LOC)
    assert out["heat.record_high_f"].value == 108
    assert out["cold.record_low_f"].value == -31
    assert out["heat.record_high_f"].provenance.station.name == "GOOD"
    assert "2024-07-14" in out["heat.record_high_f"].note


def test_acis_station_no_station_is_no_data(settings):
    out = AcisStationProvider(settings, FakeHttp(lambda *a: {"meta": []})).run_point(LOC)
    assert all(v.status is Status.NO_DATA for v in out.values())


def test_acis_snow_picks_nearest_complete_station_per_metric(settings):
    def stn(name, sid, lon, rows):
        return {"meta": {"name": name, "sids": [f"{sid} 6"], "ll": [lon, 40.0]}, "data": rows}

    n = 15  # 2011-2025
    stations = [
        stn("PATCHY", "US1XX0001", -100.01, [["M", "M"]] * 10 + [["5.0", "3"]] * 5),
        stn("SNOWONLY", "USC00000010", -100.05, [["40.0", "M"]] * n),
        stn("BOTH", "USC00000011", -100.1, [["99.0", "60"]] * n),
        stn("TOOFAR", "USC00000012", -99.0, [["1.0", "1"]] * n),
    ]
    calls = []

    def handler(method, url, payload):
        calls.append(url)
        assert url.endswith("/MultiStnData")
        assert (payload["sdate"], payload["edate"]) == ("2011", "2025")
        assert all(e["maxmissing"] == 15 for e in payload["elems"])
        return {"data": stations}

    out = AcisSnowProvider(settings, FakeHttp(handler)).run_point(LOC)
    assert len(calls) == 1  # one request for every station in the box
    assert out["winter_storm.annual_snowfall_in"].value == 40.0
    assert out["winter_storm.annual_snowfall_in"].provenance.station.name == "SNOWONLY"
    assert out["winter_storm.days_snow_depth_ge_1in"].value == 60
    assert out["winter_storm.days_snow_depth_ge_1in"].provenance.station.name == "BOTH"
    assert out["winter_storm.days_snow_depth_ge_1in"].period == "2011-2025"


def test_acis_snow_no_complete_station_is_no_data(settings):
    patchy = {
        "meta": {"name": "P", "sids": ["X 6"], "ll": [-100.0, 40.0]},
        "data": [["M", "M"]] * 15,
    }
    out = AcisSnowProvider(settings, FakeHttp(lambda *a: {"data": [patchy]})).run_point(LOC)
    assert all(v.status is Status.NO_DATA for v in out.values())
    assert "none of 1 stations" in out["winter_storm.annual_snowfall_in"].note


# --- NCEI Normals (reference only) ----------------------------------------------------------------
def _search_result(sid, lon, lat, dts):
    return {
        "filePath": f"/data/normals-annualseasonal/1991-2020/access/{sid}.csv",
        "tar": "us-climate-normals_1991-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz",
        "boundingPoints": [{"coordinates": [lon, lat], "type": "point"}],
        "stations": [{"name": sid + " NAME", "dataTypes": [{"id": d} for d in dts]}],
    }


def test_normals_reference_uses_nearest_station_carrying_each_datatype(settings):
    t90, prcp = "ANN-TMAX-AVGNDS-GRTH090", "ANN-PRCP-NORMAL"
    search = {
        "results": [
            _search_result("NEARPRCP", -100.05, 40.0, [prcp]),  # ~4 km
            _search_result("FARALL", -100.3, 40.0, [t90, prcp]),  # ~26 km
            _search_result("TOOFAR", -99.0, 40.0, [t90, prcp]),  # ~85 km, beyond radius
        ]
    }

    def handler(method, url, params):
        if "search" in url:
            return search
        assert params["stations"] == "FARALL,NEARPRCP"
        return [{"STATION": "NEARPRCP", prcp: "  -7777"}, {"STATION": "FARALL", t90: "  12.5"}]

    out = fetch_normals(FakeHttp(handler), settings, LOC, [t90, prcp])
    assert out[t90].value == 12.5 and out[t90].station.id == "FARALL"
    assert out[prcp].value == 0.0 and out[prcp].station.id == "NEARPRCP"  # trace


def test_normals_special_values():
    assert parse_value("  -7777") == (0.0, "trace (non-zero, rounds to 0)")
    assert parse_value("-9999")[0] is None
    assert parse_value("  45.2") == (45.2, None)


# --- Open Climate Risk ---------------------------------------------------------------------------
def test_ocr_outside_conus_is_no_data_without_touching_the_store(settings):
    http = FakeHttp(lambda *a: pytest.fail("should not be called"))
    honolulu = Location(id="hi", latitude=21.3, longitude=-157.86)
    out = OpenClimateRiskProvider(settings, http).run([honolulu])
    assert all(v.status is Status.NO_DATA for v in out["hi"].values())


def test_ocr_uses_point_cache(settings):
    http = FakeHttp(lambda *a: pytest.fail("no HTTP expected"))
    p = OpenClimateRiskProvider(settings, http)
    snap = settings.open_climate_risk.snapshot_id
    http.store(
        "open_climate_risk",
        p._request(snap, LOC),
        json.dumps(
            {
                "snapshot_id": snap,
                "cell_latitude": 40.0,
                "cell_longitude": -100.0,
                "values": {"bp_2011": 0.001, "bp_2047": 0.002, "rps_2011": float("nan")},
            }
        ),
    )
    out = p.run([LOC])["t"]
    assert out["wildfire.burn_probability_2011"].value == 0.001
    assert snap in out["wildfire.burn_probability_2047"].provenance.dataset_version
    assert out["wildfire.risk_to_potential_structures_2011"].status is Status.NO_DATA
