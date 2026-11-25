from pathlib import Path
import subprocess

import piexif

from dms.config import get_exiftool_path
from dms.core import analyzer
from dms.core.analyzer import analyze, _safe_append


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
    assert report.analysis_status == "unverified"
    assert analyzer.IMAGE_PARSE_WARNING in report.warnings


def test_image_thumbnail_failure_only_adds_warning(monkeypatch) -> None:
    target = FIXTURES / "test_with_gps.jpg"

    monkeypatch.setattr(analyzer, "_extract_thumbnail", lambda _path: (_ for _ in ()).throw(OSError("thumb fail")))

    report = analyze(target)

    assert analyzer.IMAGE_THUMBNAIL_WARNING in report.warnings


def test_non_ascii_metadata_is_read_with_utf8(tmp_path) -> None:
    source = tmp_path / "unicode.jpg"
    source.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())
    exif = piexif.load(str(source))
    exif["0th"][piexif.ImageIFD.Artist] = b"\xe2\x98\x80 \xd0\x98\xd0\xb2\xd0\xb0\xd0\xbd"
    piexif.insert(piexif.dump(exif), str(source))

    report = analyze(source)

    assert report.analysis_status == "ok"
    assert report.analysis_error is None
    artist = report.by_key()["Artist"]
    assert artist.value == "\u2600 \u0418\u0432\u0430\u043d"
    assert artist.is_sensitive is True


def test_quicktime_container_tags_are_not_sensitive() -> None:
    fields: list[analyzer.MetaField] = []
    _safe_append(fields, "QuickTime:TimeScale", 1000)
    _safe_append(fields, "QuickTime:HandlerDescription", "VideoHandler")
    _safe_append(fields, "QuickTime:CompositionTimeToSample", "(Binary data 88 bytes)")

    assert [field.is_sensitive for field in fields] == [False, False, False]
    assert all(field.status == "clean" for field in fields)


def test_zero_quicktime_dates_are_not_sensitive_but_real_dates_are() -> None:
    fields: list[analyzer.MetaField] = []
    _safe_append(fields, "QuickTime:TrackCreateDate", "0000:00:00 00:00:00")
    _safe_append(fields, "QuickTime:TrackModifyDate", "0000:00:00 00:00:00")
    _safe_append(fields, "QuickTime:CreateDate", "2024:04:18 10:22:33")

    assert fields[0].is_sensitive is False
    assert fields[1].is_sensitive is False
    assert fields[2].is_sensitive is True
    assert fields[2].status == "risk"


def test_zip_container_timestamps_are_not_sensitive() -> None:
    fields: list[analyzer.MetaField] = []
    _safe_append(fields, "ZIP:ZipModifyDate", "1980:01:01 00:00:00")
    _safe_append(fields, "ZIP:ZipCreateDate", "1980:01:01 00:00:00")

    assert [field.is_sensitive for field in fields] == [False, False]


def test_same_tag_name_in_different_groups_is_not_deduplicated(tmp_path) -> None:
    exiftool = get_exiftool_path()
    if not exiftool:
        return
    source = tmp_path / "duplicate.jpg"
    source.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())
    subprocess.run(
        [
            exiftool,
            "-overwrite_original",
            "-m",
            "-IFD0:Software=DMS Test",
            "-XMP-tiff:Software=DMS Test",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    report = analyze(source)
    software_tags = {field.exiftool_tag for field in report.fields if field.key == "Software"}

    assert {"IFD0:Software", "XMP-tiff:Software"} <= software_tags
