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


def test_gui_get_log_path_falls_back_to_temp_on_permission_error(tmp_path, monkeypatch) -> None:
    import tempfile
    from dms.interfaces.gui import app as gui_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gui_app.sys, "frozen", False, raising=False)

    orig_touch = Path.touch

    def deny_cwd_touch(self, *args, **kwargs):
        if self.parent == tmp_path:
            raise PermissionError("read-only")
        return orig_touch(self, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", deny_cwd_touch)

    log_path = gui_app.get_log_path()
    assert log_path == Path(tempfile.gettempdir()) / "dms_errors.log"


def test_cleanup_stale_temp_dirs_removes_dead_pid_and_keeps_live_pid(tmp_path) -> None:
    from dms.interfaces.gui.app import cleanup_stale_temp_dirs

    dead_dir = tmp_path / "dms_dead123"
    dead_dir.mkdir()
    (dead_dir / ".dms.pid").write_text("99999999", encoding="utf-8")
    (dead_dir / "leak.jpg").write_bytes(b"secret")

    live_dir = tmp_path / "dms_live123"
    live_dir.mkdir()
    (live_dir / ".dms.pid").write_text(str(os.getpid()), encoding="utf-8")

    removed = cleanup_stale_temp_dirs(tmp_path)

    assert removed == 1
    assert not dead_dir.exists()
    assert live_dir.exists()


def test_plan_batch_destinations_handles_spoof_suffix_and_name_collisions(tmp_path) -> None:
    from dms.interfaces.gui.app import _plan_batch_destinations

    s1 = FileSession(
        original_path=tmp_path / "dir1" / "photo.jpg",
        work_path=tmp_path / "w1.jpg",
        original_report=_report(tmp_path / "w1.jpg", []),
        current_report=_report(tmp_path / "w1.jpg", []),
        output_suffix="spoofed",
    )
    s2 = FileSession(
        original_path=tmp_path / "dir2" / "photo.jpg",
        work_path=tmp_path / "w2.jpg",
        original_report=_report(tmp_path / "w2.jpg", []),
        current_report=_report(tmp_path / "w2.jpg", []),
        output_suffix="spoofed",
    )

    out_dir = tmp_path / "out"
    plan = _plan_batch_destinations([s1, s2], out_dir)

    assert [dest.name for _, dest in plan] == ["photo_spoofed.jpg", "photo_2_spoofed.jpg"]


def test_open_batch_defers_temp_copy_from_ui_thread(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        f1.write_bytes(b"a")
        f2.write_bytes(b"b")

        window.open_batch([f1, f2])

        assert len(window.batch_sessions) == 2
        assert all(s.temp_dir is None for s in window.batch_sessions)
    finally:
        window.close()


def test_save_all_batch_prompts_before_overwriting_existing_files(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        existing = out_dir / "photo_spoofed.jpg"
        existing.write_bytes(b"KEEP_EXISTING")

        work = tmp_path / "work.jpg"
        work.write_bytes(b"NEW_DATA")
        window.batch_sessions = [
            FileSession(
                original_path=tmp_path / "photo.jpg",
                work_path=work,
                original_report=_report(work, []),
                current_report=_report(work, []),
                is_modified=True,
                output_suffix="spoofed",
            )
        ]

        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(out_dir))
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)

        assert window.save_all_batch() is False
        assert existing.read_bytes() == b"KEEP_EXISTING"
        assert window.batch_sessions[0].is_modified is True
    finally:
        window.close()


def test_locales_are_complete_translated_and_keep_placeholders() -> None:
    import string
    from dms.interfaces.gui.theme import LOCALES

    neutral_keys = {"app_title", "full_title", "drop_formats"}
    en = LOCALES["en"]
    formatter = string.Formatter()

    def placeholders(text: str) -> set[str]:
        return {fname for _, fname, _, _ in formatter.parse(text) if fname is not None}

    for lang in ("ru", "zh"):
        bucket = LOCALES[lang]
        assert set(bucket) == set(en)
        identical = {key for key, value in en.items() if bucket[key] == value}
        assert identical <= neutral_keys, f"{lang} has untranslated keys: {sorted(identical - neutral_keys)}"
        for key, en_val in en.items():
            assert placeholders(bucket[key]) == placeholders(en_val), f"{lang}.{key} placeholder mismatch"


def test_spoof_editor_gps_validates_range_and_non_gps_value_error(tmp_path) -> None:
    from dms.interfaces.gui.widgets.spoof_editor import SpoofEditor

    app = QApplication.instance() or QApplication([])
    editor = SpoofEditor(lambda: "en")
    errors: list[str] = []
    editor.validationError.connect(errors.append)

    gps_field = _field("GPSLatitude", category="gps", exiftool_tag="EXIF:GPSLatitude")
    report = _report(tmp_path / "photo.jpg", [gps_field])
    editor.set_context(report, gps_field)
    editor.lat_edit.setText("999")
    editor.lon_edit.setText("999")
    editor._emit_apply()

    assert errors == ["gps_invalid_coords"]

    errors.clear()
    text_field = _field("Artist", category="author", exiftool_tag="EXIF:Artist")
    editor.set_context(_report(tmp_path / "photo.jpg", [text_field]), text_field)
    editor._text_payload = lambda: (_ for _ in ()).throw(ValueError("bad text"))
    editor._emit_apply()

    assert errors == ["unexpected_error"]


def test_screen_report_falls_back_on_corrupted_thumbnail(tmp_path) -> None:
    from dms.interfaces.gui.screens.screen_report import ScreenReport

    app = QApplication.instance() or QApplication([])
    screen = ScreenReport(lambda: "en")
    photo = tmp_path / "corrupt_thumb.dng"
    photo.write_bytes(b"raw")
    report = FileReport(path=photo, file_type="raw", fields=[], thumbnail=b"not-a-valid-image")

    screen.set_report(report, {}, display_path=photo)

    assert "RAW" in screen.preview_label.text()
