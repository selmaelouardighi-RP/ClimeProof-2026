"""Live smoke tests against the real public APIs. Run with:  pytest -m live

Uses public civic landmarks (city halls), never a facility.
"""

import pytest

from climeproof.http import CachedHttp
from climeproof.pipeline import record_fingerprint, run
from climeproof.providers import REGISTRY
from climeproof.schema import Location, Status

pytestmark = pytest.mark.live

PHOENIX = Location(id="phoenix_city_hall", latitude=33.4484, longitude=-112.0740)
MINNEAPOLIS = Location(id="minneapolis_city_hall", latitude=44.9778, longitude=-93.2650)
HTTP_ONLY = {k: v for k, v in REGISTRY.items() if k != "open_climate_risk"}


def test_recent_climate_profiles(settings):
    http = CachedHttp(settings.pipeline.cache_dir, settings.pipeline.user_agent)
    phx, msp = run([PHOENIX, MINNEAPOLIS], settings, http, registry=HTTP_ONLY)

    # Desert stations report snow depth patchily (Phoenix airport: 12 of 15 recent years), so
    # NO_DATA there is the correct answer under the coverage rule, not a failure.
    allowed_gaps = {("phoenix_city_hall", "winter_storm.days_snow_depth_ge_1in")}
    for rec in (phx, msp):
        not_ok = {
            k: v.note
            for k, v in rec.metrics.items()
            if v.status not in (Status.OK, Status.NOT_IMPLEMENTED)
            and (rec.location.id, k) not in allowed_gaps
        }
        assert not not_ok, (rec.location.id, not_ok)
        assert rec.metrics["heat.days_ge_100f"].period == settings.periods.recent_label

    p, m = phx.metrics, msp.metrics
    assert 80 < p["heat.days_ge_100f"].value < 160
    assert p["heat.days_ge_90f"].value > p["heat.days_ge_100f"].value > p["heat.days_ge_105f"].value
    assert p["heat.record_high_f"].value >= 118
    assert 4 < p["extreme_precip.annual_precip_in"].value < 14
    assert 20 < m["winter_storm.annual_snowfall_in"].value < 90
    assert 100 < m["cold.freeze_days"].value < 200
    assert m["cold.heating_degree_days"].value > 5000 > p["cold.heating_degree_days"].value

    # Rerunning from the cache gives the identical record (audit trail intact).
    offline = CachedHttp(settings.pipeline.cache_dir, settings.pipeline.user_agent, offline=True)
    again = run([PHOENIX, MINNEAPOLIS], settings, offline, registry=HTTP_ONLY)
    assert [record_fingerprint(r) for r in again] == [record_fingerprint(r) for r in (phx, msp)]
