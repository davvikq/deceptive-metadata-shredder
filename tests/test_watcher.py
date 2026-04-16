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

    def fake_remove_all(report: FileReport, output_path=None):
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

    def fake_remove_all(report: FileReport, output_path=None):
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

    def fake_remove_all(report: FileReport, output_path=None):
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
