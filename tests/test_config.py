from datetime import date

import pytest

from climeproof.config import load_settings


def test_recent_window_rolls_with_the_calendar():
    p = load_settings(today=date(2026, 10, 16)).periods
    assert (p.recent_label, p.trend_label, p.records_end) == (
        "2011-2025",
        "1996-2025",
        "2026-10-15",
    )
    p = load_settings(today=date(2027, 1, 5)).periods
    assert (p.recent_label, p.trend_label) == ("2012-2026", "1997-2026")


def test_pinned_end_year_recreates_an_earlier_run():
    s = load_settings(today=date(2026, 10, 16))
    s.periods.end_year = 2024
    s.periods.resolve(date(2026, 10, 16))
    assert (s.periods.recent_label, s.periods.records_end) == ("2010-2024", "2024-12-31")


def test_end_year_must_be_complete():
    s = load_settings(today=date(2026, 10, 16))
    s.periods.end_year = 2026
    with pytest.raises(ValueError):
        s.periods.resolve(date(2026, 10, 16))
