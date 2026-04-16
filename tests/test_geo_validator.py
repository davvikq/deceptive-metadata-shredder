from dms.core.geo_validator import get_country, smart_spoof


def test_moscow_is_in_russia() -> None:
    assert get_country(55.75, 37.61) == "RU"


def test_smart_spoof_keeps_coordinate_in_same_country() -> None:
    lat, lon = smart_spoof(55.75, 37.61)
    assert get_country(lat, lon) == "RU"


def test_ocean_coordinate_fallback_does_not_crash() -> None:
    lat, lon = smart_spoof(0.0, -140.0)
    assert isinstance(lat, float)
    assert isinstance(lon, float)
