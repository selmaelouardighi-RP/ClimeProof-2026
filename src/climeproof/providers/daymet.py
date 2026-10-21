"""NASA/ORNL Daymet V4 R1 (1 km daily grid) via the Single Pixel Extraction API.

Used in iteration 1 as an independent gridded cross-check (`climeproof compare`), not as the
primary source of any record field. API: https://daymet.ornl.gov/web_services
Note: Daymet uses a 365-day year (Dec 31 dropped in leap years).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict

from ..config import Settings
from ..http import CachedHttp, CachedResponse

SOURCE = "daymet"


def fetch_daily(
    http: CachedHttp, settings: Settings, lat: float, lon: float, variables: str = "tmax,tmin,prcp"
) -> tuple[list[dict[str, float]], CachedResponse]:
    per = settings.periods
    resp = http.get(
        SOURCE,
        settings.daymet.url,
        {
            "lat": f"{lat:.5f}",
            "lon": f"{lon:.5f}",
            "vars": variables,
            "start": f"{per.recent_start}-01-01",
            "end": f"{per.recent_end}-12-31",
        },
    )
    text = resp.text
    header_at = text.find("year,yday")
    if header_at < 0:
        raise RuntimeError(f"unexpected Daymet response: {text[:200]!r}")
    rows = [
        {k: float(v) for k, v in r.items()} for r in csv.DictReader(io.StringIO(text[header_at:]))
    ]
    return rows, resp


def annual_mean_days_tmax_ge(
    rows: list[dict[str, float]], thresholds_f: list[float]
) -> dict[float, float]:
    per_year: dict[int, dict[float, int]] = defaultdict(lambda: dict.fromkeys(thresholds_f, 0))
    for r in rows:
        tmax_f = r["tmax (deg c)"] * 9 / 5 + 32
        counts = per_year[int(r["year"])]
        for t in thresholds_f:
            counts[t] += tmax_f >= t
    n = len(per_year)
    return {t: sum(c[t] for c in per_year.values()) / n for t in thresholds_f} if n else {}
