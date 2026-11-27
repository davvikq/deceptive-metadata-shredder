from pathlib import Path
from types import SimpleNamespace

from dms.core.models import FileReport
from dms.interfaces import watcher
from dms.interfaces.watcher import DMSEventHandler


def test_new_file_creates_cleaned_copy(tmp_path, monkeypatch) -> None:
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg")

    def fake_analyze(path: Path) -> FileReport:
        return FileReport(path=Path(path), file_type="jpeg", fields=[], thumbnail=None)

    def fake_remove_all(report: FileReport, output_path=None, **_kwargs):
        cleaned = (
            output_path
            if output_path is not None
            else report.path.with_name(f"{report.path.stem}_cleaned{report.path.suffix}")
        )
        cleaned.parent.mkdir(parents=True, exist_ok=True)
        cleaned.write_bytes(report.path.read_bytes())
        return cleaned

    monkeypatch.setattr(watcher.analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(watcher, "remove_all", fake_remove_all)

    processed: list[tuple[Path, int, bool]] = []
    handler = DMSEventHandler(mode="clean", callback=lambda path, fields, ok: processed.append((path, fields, ok)))
    monkeypatch.setattr(handler, "_wait_until_stable", lambda path: True)
    monkeypatch.setattr(watcher.time, "sleep", lambda *_args, **_kwargs: None)

    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(source)))
    handler._task_queue.join()

    assert source.with_name("image_cleaned.jpg").exists()
    assert processed == [(source, 0, True)]


def test_collect_subfolder_writes_under_dms_cleaned(tmp_path, monkeypatch) -> None:
    source = tmp_path / "image.jpg"
    source.write_bytes(b"jpeg")
    out_dir = tmp_path / "dms_cleaned"

    def fake_analyze(path: Path) -> FileReport:
        return FileReport(path=Path(path), file_type="jpeg", fields=[], thumbnail=None)

    def fake_remove_all(report: FileReport, output_path=None, **_kwargs):
        cleaned = (
            output_path
            if output_path is not None
            else report.path.with_name(f"{report.path.stem}_cleaned{report.path.suffix}")
        )
        cleaned.parent.mkdir(parents=True, exist_ok=True)
        cleaned.write_bytes(report.path.read_bytes())
        return cleaned

    monkeypatch.setattr(watcher.analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(watcher, "remove_all", fake_remove_all)

    processed: list[tuple[Path, int, bool]] = []
    handler = DMSEventHandler(
        mode="clean",
        callback=lambda path, fields, ok: processed.append((path, fields, ok)),
        output_dir=out_dir,
    )
    monkeypatch.setattr(handler, "_wait_until_stable", lambda path: True)
    monkeypatch.setattr(watcher.time, "sleep", lambda *_args, **_kwargs: None)

    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(source)))
    handler._task_queue.join()

    assert (out_dir / "image_cleaned.jpg").exists()
    assert not source.with_name("image_cleaned.jpg").exists()
    assert processed == [(source, 0, True)]


def test_cleaned_file_is_ignored_and_not_reprocessed(tmp_path, monkeypatch) -> None:
    cleaned = tmp_path / "image_cleaned.jpg"
    cleaned.write_bytes(b"jpeg")

    called: list[str] = []
    handler = DMSEventHandler(mode="clean", callback=lambda *_args: called.append("callback"))
    monkeypatch.setattr(handler, "process", lambda path: called.append(str(path)))

    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(cleaned)))

    assert called == []


def test_file_inside_dms_cleaned_is_ignored_even_with_include_all(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "dms_cleaned"
    out_dir.mkdir()
    inside = out_dir / "drop.jpg"
    inside.write_bytes(b"jpeg")

    called: list[str] = []
    handler = DMSEventHandler(
        mode="clean",
        callback=lambda *_args: called.append("cb"),
        output_dir=out_dir,
        include_all=True,
    )
    monkeypatch.setattr(handler, "process", lambda path: called.append(str(path)))

    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(inside)))

    assert called == []


def test_include_all_processes_cleaned_suffix_into_subfolder(tmp_path, monkeypatch) -> None:
    source = tmp_path / "image_cleaned.jpg"
    source.write_bytes(b"jpeg")
    out_dir = tmp_path / "dms_cleaned"

    def fake_analyze(path: Path) -> FileReport:
        return FileReport(path=Path(path), file_type="jpeg", fields=[], thumbnail=None)

    def fake_remove_all(report: FileReport, output_path=None, **_kwargs):
        cleaned = (
            output_path
            if output_path is not None
            else report.path.with_name(f"{report.path.stem}_cleaned{report.path.suffix}")
        )
        cleaned.parent.mkdir(parents=True, exist_ok=True)
        cleaned.write_bytes(report.path.read_bytes())
        return cleaned

    monkeypatch.setattr(watcher.analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(watcher, "remove_all", fake_remove_all)

    processed: list[tuple[Path, int, bool]] = []
    handler = DMSEventHandler(
        mode="clean",
        callback=lambda path, fields, ok: processed.append((path, fields, ok)),
        output_dir=out_dir,
        include_all=True,
    )
    monkeypatch.setattr(handler, "_wait_until_stable", lambda path: True)
    monkeypatch.setattr(watcher.time, "sleep", lambda *_args, **_kwargs: None)

    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(source)))
    handler._task_queue.join()

    assert (out_dir / "image_cleaned_cleaned.jpg").exists()
    assert processed == [(source, 0, True)]


def test_watcher_forwards_pdf_strip_flags(tmp_path, monkeypatch) -> None:
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4")
    received: list[tuple[bool, bool]] = []

    def fake_analyze(path: Path) -> FileReport:
        return FileReport(path=Path(path), file_type="pdf", fields=[], thumbnail=None)

    def fake_remove_all(
        report: FileReport,
        output_path=None,
        *,
        strip_annotations: bool = False,
        strip_attachments: bool = False,
    ):
        received.append((strip_annotations, strip_attachments))
        cleaned = output_path or report.path.with_name(f"{report.path.stem}_cleaned{report.path.suffix}")
        cleaned.write_bytes(report.path.read_bytes())
        return cleaned

    monkeypatch.setattr(watcher.analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(watcher, "remove_all", fake_remove_all)

    handler = DMSEventHandler(mode="clean", strip_annotations=True, strip_attachments=True)
    handler.process(source)

    assert received == [(True, True)]


def test_watcher_spoof_clean_strips_residual_signature_and_restores_dates(tmp_path, monkeypatch) -> None:
    import subprocess
    from datetime import datetime
    from dms.core.models import MetaField

    source = tmp_path / "photo.jpg"
    source.write_bytes(b"jpeg")
    dest = tmp_path / "photo_spoofed.jpg"

    before_report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:DateTimeOriginal", "DateTimeOriginal", "Create Date", "2023:01:01 10:00:00", "dates", True, True, is_computed=False, status="risk"),
            MetaField("XMP:Rights", "Rights", "Rights", "Secret Owner", "other", True, True, is_computed=False, status="risk"),
        ],
    )
    after_spoof_report = FileReport(
        path=dest,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:DateTimeOriginal", "DateTimeOriginal", "Create Date", "2021:05:10 08:30:00", "dates", True, True, is_computed=False, status="risk"),
            MetaField("XMP:Rights", "Rights", "Rights", "Secret Owner", "other", True, True, is_computed=False, status="risk"),
        ],
    )

    def fake_analyze(path: Path) -> FileReport:
        return after_spoof_report if Path(path) == dest else before_report

    def fake_apply_smart_spoof(report: FileReport, output_path: Path | None = None):
        out = output_path or report.path.with_name("photo_spoofed.jpg")
        out.write_bytes(b"spoofed")
        return out, ["dates"], []

    exiftool_calls: list[list[str]] = []
    sig_calls: list[Path] = []
    fs_calls: list[tuple[Path, datetime]] = []

    monkeypatch.setattr(watcher.analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(watcher, "apply_smart_spoof", fake_apply_smart_spoof)
    monkeypatch.setattr(watcher, "require_exiftool", lambda: "exiftool")
    monkeypatch.setattr(
        watcher.subprocess,
        "run",
        lambda args, **_kwargs: exiftool_calls.append(list(args)) or subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(watcher, "remove_exiftool_signature", lambda p, _et: sig_calls.append(p))
    monkeypatch.setattr(watcher, "set_filesystem_dates", lambda p, dt: fs_calls.append((p, dt)))

    handler = DMSEventHandler(mode="spoof_clean")
    handler.process(source)

    assert len(exiftool_calls) == 1
    assert "-m" in exiftool_calls[0]
    assert "-XMP:Rights=" in exiftool_calls[0]
    assert sig_calls == [dest]
    assert fs_calls == [(dest, datetime(2021, 5, 10, 8, 30, 0))]
