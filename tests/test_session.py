import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from dms.core.models import FileReport, MetaField
from dms.interfaces.gui.app import FileSession, MainWindow


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _field(
    key: str,
    *,
    category: str,
    sensitive: bool = True,
    exiftool_tag: str | None = None,
) -> MetaField:
    return MetaField(
        exiftool_tag=exiftool_tag or key,
        key=key,
        label=key,
        value="value",
        category=category,
        spoofable=True,
        is_sensitive=sensitive,
    )


def _report(path: Path, fields: list[MetaField]) -> FileReport:
    return FileReport(path=path, file_type=path.suffix.lstrip(".") or "jpeg", fields=fields)


def test_file_session_keeps_original_untouched(tmp_path) -> None:
    original = tmp_path / "photo.jpg"
    work = tmp_path / "photo_cleaned.jpg"
    original.write_bytes(b"original")
    work.write_bytes(original.read_bytes())

    session = FileSession(
        original_path=original,
        work_path=work,
        original_report=_report(original, []),
        current_report=_report(work, []),
        temp_dir=tmp_path,
    )

    session.work_path.write_bytes(b"changed")

    assert session.original_path.read_bytes() == b"original"
    assert session.work_path.read_bytes() == b"changed"


def test_spoofed_keys_expand_after_each_operation(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        original = tmp_path / "photo.jpg"
        work = tmp_path / "photo_cleaned.jpg"
        original.write_bytes(b"x")
        work.write_bytes(b"x")
        report = _report(
            work,
            [
                _field("GPSLatitude", category="gps", exiftool_tag="EXIF:GPSLatitude"),
                _field("GPSPosition", category="gps", exiftool_tag="Composite:GPSPosition"),
                _field("Author", category="author", exiftool_tag="XMP:Author"),
                _field("Creator", category="author", exiftool_tag="XMP:Creator"),
            ],
        )
        window.session = FileSession(
            original_path=original,
            work_path=work,
            original_report=report,
            current_report=report,
            temp_dir=tmp_path,
        )

        window._record_session_changes({"GPSLatitude"}, "spoofed")
        window._record_session_changes({"Author"}, "spoofed")

        assert "gpslatitude" in window.session.spoofed_keys
        assert "gpsposition" in window.session.spoofed_keys
        assert "author" in window.session.spoofed_keys
        assert "creator" in window.session.spoofed_keys
    finally:
        window.close()


def test_risk_score_recalculates_from_field_status(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        original = tmp_path / "photo.jpg"
        work = tmp_path / "photo_cleaned.jpg"
        original.write_bytes(b"x")
        work.write_bytes(b"x")
        report = _report(
            work,
            [
                _field("GPSLatitude", category="gps", exiftool_tag="EXIF:GPSLatitude"),
                _field("GPSLongitude", category="gps", exiftool_tag="EXIF:GPSLongitude"),
                _field("Author", category="author", exiftool_tag="XMP:Author"),
                _field("SerialNumber", category="device", exiftool_tag="EXIF:SerialNumber"),
                _field("ImageWidth", category="other", sensitive=False, exiftool_tag="EXIF:ImageWidth"),
            ],
        )
        window.session = FileSession(
            original_path=original,
            work_path=work,
            original_report=report,
            current_report=report,
            temp_dir=tmp_path,
        )
        window.session.spoofed_keys.update(window._expand_linked_keys("GPSLatitude"))
        window.session.removed_keys.update(window._expand_linked_keys("Author"))

        window._apply_session_states(report)
        risk_count = sum(1 for field in report.fields if field.status == "risk")

        assert risk_count == 1
        assert report.by_key()["GPSLatitude"].status == "spoofed"
        assert report.by_key()["Author"].status == "removed"
        assert report.by_key()["SerialNumber"].status == "risk"
        assert report.by_key()["ImageWidth"].status == "clean"
    finally:
        window.close()
