import pytest

from climeproof.climate_stats import count_runs, mean_with_coverage, percentile, trend_per_decade


def test_mean_respects_coverage():
    assert mean_with_coverage([1, 2, 3, None], 0.75) == 2
    assert mean_with_coverage([1, None, None, None], 0.75) is None
    assert mean_with_coverage([], 0.5) is None


def test_trend_per_decade():
    years = list(range(1991, 2021))
    assert trend_per_decade(years, [2 * (y - 1991) for y in years], 0.9) == pytest.approx(20.0)
    assert trend_per_decade(years, [5] * 30, 0.9) == 0.0
    assert trend_per_decade(years, [None] * 30, 0.9) is None


def test_percentile_matches_linear_interpolation():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile(list(range(101)), 95) == 95
    with pytest.raises(ValueError):
        percentile([], 50)


def test_count_runs():
    T, F = True, False
    assert count_runs([T, T, T, F, T, T, F, T, T, T, T], 3) == 2
    assert count_runs([T, T, None, T, T], 3) == 0  # missing breaks a run
    assert count_runs([T, T, T], 3) == 1  # run at end of series counts
