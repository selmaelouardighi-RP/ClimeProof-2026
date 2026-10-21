"""Pure, deterministic statistics used by providers (unit-tested without network)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


def mean_with_coverage(values: Sequence[float | None], min_coverage: float) -> float | None:
    """Mean of non-missing values, or None if too few years are valid."""
    valid = [v for v in values if v is not None]
    if not values or len(valid) / len(values) < min_coverage:
        return None
    return statistics.fmean(valid)


def trend_per_decade(
    years: Sequence[int], values: Sequence[float | None], min_coverage: float
) -> float | None:
    """Ordinary-least-squares slope, scaled to units per decade."""
    pairs = [(y, v) for y, v in zip(years, values, strict=True) if v is not None]
    if not values or len(pairs) / len(values) < min_coverage or len(pairs) < 3:
        return None
    xs, ys = zip(*pairs, strict=True)
    if len(set(ys)) == 1:
        return 0.0
    return statistics.linear_regression(xs, ys).slope * 10


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile (same as numpy's default 'linear' method)."""
    xs = sorted(values)
    if not xs:
        raise ValueError("percentile of empty sequence")
    k = (len(xs) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def count_runs(flags: Sequence[bool | None], min_length: int) -> int:
    """Number of runs of >= min_length consecutive True values. Missing (None) breaks a run."""
    events, run = 0, 0
    for f in flags:
        if f:
            run += 1
        else:
            if run >= min_length:
                events += 1
            run = 0
    if run >= min_length:
        events += 1
    return events
