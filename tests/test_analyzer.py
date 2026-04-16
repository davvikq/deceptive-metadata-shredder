from pathlib import Path

from dms.core import analyzer
from dms.core.analyzer import analyze


FIXTURES = Path(__file__).parent / "fixtures"


def test_gps_is_parsed_from_jpeg_fixture() -> None:
    report = analyze(FIXTURES / "test_with_gps.jpg")
    fields = report.by_key()

    assert "GPSLatitude" in fields
    assert "GPSLongitude" in fields
    assert abs(float(fields["GPSLatitude"].value) - 55.7522) < 0.01
    assert abs(float(fields["GPSLongitude"].value) - 37.6156) < 0.01


def test_expected_categories_are_present() -> None:
    report = analyze(FIXTURES / "test_with_gps.jpg")
    categories = {field.category for field in report.fields}

    assert {"gps", "device", "dates"}.issubset(categories)


def test_sensitive_flag_marks_privacy_relevant_fields() -> None:
    report = analyze(FIXTURES / "test_with_gps.jpg")
    gps_field = report.by_key()["GPSLatitude"]

    assert gps_field.is_sensitive is True


def test_technical_camera_tags_are_not_marked_sensitive() -> None:
    report = analyze(FIXTURES / "test_with_gps.jpg")
    width_field = report.by_key()["ImageWidth"]

    assert width_field.is_sensitive is False


def test_webp_metadata_is_parsed() -> None:
    report = analyze(FIXTURES / "test_with_metadata.webp")
    fields = report.by_key()

    assert report.file_type == "webp"
    assert "Make" in fields
    assert "DateTimeOriginal" in fields


def test_tiff_metadata_is_parsed() -> None:
    report = analyze(FIXTURES / "test_with_metadata.tiff")
    fields = report.by_key()

    assert report.file_type == "tiff"
    assert "Make" in fields
    assert "DateTimeOriginal" in fields


def test_image_analysis_falls_back_when_primary_and_fallback_fail(monkeypatch) -> None:
    target = FIXTURES / "test_with_gps.jpg"

    monkeypatch.setattr(analyzer, "_analyze_with_exiftool", lambda _path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(analyzer, "_analyze_image_fallback", lambda _path: (_ for _ in ()).throw(OSError("bad image")))
    monkeypatch.setattr(analyzer, "_extract_thumbnail", lambda _path: b"thumb")

    report = analyze(target)

    assert report.file_type == "jpeg"
    assert report.fields == []
    assert analyzer.IMAGE_PARSE_WARNING in report.warnings


def test_image_thumbnail_failure_only_adds_warning(monkeypatch) -> None:
    target = FIXTURES / "test_with_gps.jpg"

    monkeypatch.setattr(analyzer, "_extract_thumbnail", lambda _path: (_ for _ in ()).throw(OSError("thumb fail")))

    report = analyze(target)

    assert analyzer.IMAGE_THUMBNAIL_WARNING in report.warnings
