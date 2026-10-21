"""Small geodesy helpers (no GIS dependency needed for point work)."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """(west, south, east, north) box that contains the circle of `radius_km`."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


# Rough CONUS envelope, used to mark CONUS-only datasets as NO_DATA elsewhere.
CONUS_BOUNDS = (-125.0, 24.4, -66.9, 49.5)


def in_conus(lat: float, lon: float) -> bool:
    w, s, e, n = CONUS_BOUNDS
    return w <= lon <= e and s <= lat <= n
