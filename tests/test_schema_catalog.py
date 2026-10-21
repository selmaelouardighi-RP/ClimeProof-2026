import pytest
from pydantic import ValidationError

from climeproof.catalog import HAZARDS, HAZARDS_BY_ID, METRICS, metrics_for_provider
from climeproof.providers import REGISTRY
from climeproof.schema import MetricValue, Status

from .conftest import FIXED_TIME


def test_ok_requires_value_and_provenance():
    with pytest.raises(ValidationError):
        MetricValue(status=Status.OK)
    with pytest.raises(ValidationError):
        MetricValue(status=Status.OK, value=1.0)


def test_non_ok_must_not_carry_value():
    with pytest.raises(ValidationError):
        MetricValue(status=Status.NO_DATA, value=1.0)
    assert MetricValue(status=Status.NOT_APPLICABLE).value is None


def test_na_and_no_data_are_distinct_states():
    assert Status.NOT_APPLICABLE != Status.NO_DATA


def test_metric_ids_unique_and_well_formed():
    ids = [m.id for m in METRICS]
    assert len(ids) == len(set(ids))
    for m in METRICS:
        assert m.hazard in HAZARDS_BY_ID, m.id


def test_every_scope_hazard_has_at_least_one_metric():
    covered = {m.hazard for m in METRICS}
    assert {h.id for h in HAZARDS} == covered


def test_every_named_provider_is_registered():
    for name in {m.provider for m in METRICS if m.provider}:
        assert name in REGISTRY, name
        assert metrics_for_provider(name)


def test_fixed_time_is_timezone_aware():
    assert FIXED_TIME.tzinfo is not None
