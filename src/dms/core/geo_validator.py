"""Offline geographic validation and spoofing helpers."""

from __future__ import annotations

import json
import random
from functools import lru_cache

from shapely.geometry import Point, shape

from dms.config import DATA_DIR

NEUTRAL_WATERS = (0.0, -160.0)


@lru_cache(maxsize=1)
def _load_features() -> list[dict]:
    payload = json.loads((DATA_DIR / "countries.geojson").read_text(encoding="utf-8"))
    return payload["features"]


def has_country_data() -> bool:
    """Return whether the offline country dataset is available."""

    return (DATA_DIR / "countries.geojson").exists()


@lru_cache(maxsize=1)
def _load_geometries() -> list[tuple[str, object, tuple[float, float, float, float]]]:
    items: list[tuple[str, object, tuple[float, float, float, float]]] = []
    for feature in _load_features():
        code = (
            feature["properties"].get("ISO_A2")
            or feature["properties"].get("iso_a2")
            or feature["properties"].get("ADM0_A3")
            or "XX"
        )
        geometry = shape(feature["geometry"])
        items.append((code, geometry, geometry.bounds))
    return items


def get_country(lat: float, lon: float) -> str:
    """Return the country code for the given coordinate."""

    point = Point(lon, lat)
    for code, geometry, _bounds in _load_geometries():
        if geometry.contains(point) or geometry.touches(point):
            return code
    return "ZZ"


def get_random_point_in_country(country_code: str) -> tuple[float, float]:
    """Return a guaranteed point inside the requested country polygon."""

    matches = [
        (geometry, bounds)
        for code, geometry, bounds in _load_geometries()
        if code.upper() == country_code.upper()
    ]
    if not matches:
        return NEUTRAL_WATERS

    geometry, bounds = random.choice(matches)
    min_lon, min_lat, max_lon, max_lat = bounds
    for _ in range(5000):
        lon = random.uniform(min_lon, max_lon)
        lat = random.uniform(min_lat, max_lat)
        point = Point(lon, lat)
        if geometry.contains(point) or geometry.touches(point):
            return (round(lat, 6), round(lon, 6))

    representative = geometry.representative_point()
    return (round(representative.y, 6), round(representative.x, 6))


def smart_spoof(lat: float, lon: float) -> tuple[float, float]:
    """
    Randomize coordinates but keep the same country when detectable.
    Unknown country → NEUTRAL_WATERS (open ocean).
    """

    country = get_country(lat, lon)
    base_lat, base_lon = (
        get_random_point_in_country(country) if country != "ZZ" else NEUTRAL_WATERS
    )
    jittered = (base_lat + random.uniform(-0.001, 0.001), base_lon + random.uniform(-0.001, 0.001))
    spoof_country = get_country(*jittered)
    if country != "ZZ" and spoof_country != country:
        return get_random_point_in_country(country)
    return (round(jittered[0], 6), round(jittered[1], 6))
