from pathlib import Path

from typer.testing import CliRunner

from dms.core.models import FileReport, MetaField
from dms.interfaces import cli
from dms.interfaces.gui.app import looks_like_dms_output


runner = CliRunner()


def _report(path: Path, *, status: str = "ok", error: str | None = None) -> FileReport:
    return FileReport(
        path=path,
        file_type="jpeg",
        analysis_status=status,
        analysis_error=error,
        fields=[
            MetaField(
                exiftool_tag="EXIF:GPSLatitude",
                key="GPSLatitude",
                label="GPS Latitude",
                value="55.75",
                category="gps",
                spoofable=True,
                is_sensitive=True,
                status="risk",
            )
        ],
    )


def test_batch_processes_multiple_files(tmp_path, monkeypatch) -> None:
    file_a = tmp_path / "a.jpg"
    file_b = tmp_path / "b.jpg"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")

    processed: list[str] = []

    def fake_process_clean(file: Path, output: Path | None = None):
        processed.append(file.name)
        result = output or file.with_name(f"{file.stem}_cleaned{file.suffix}")
        result.write_bytes(file.read_bytes())
        return result, 3

    monkeypatch.setattr(cli.analyzer, "analyze", lambda path: _report(Path(path)))
    monkeypatch.setattr(cli.analyzer, "verify", lambda path: [])
    monkeypatch.setattr(cli, "_process_clean", fake_process_clean)

    result = runner.invoke(cli.app, ["batch", str(file_a), str(file_b), "--mode", "clean", "--yes"])

    assert result.exit_code == 0
    assert processed == ["a.jpg", "b.jpg"]
    assert "2 succeeded" in result.output


def test_batch_continues_when_one_file_fails(tmp_path, monkeypatch) -> None:
    good = tmp_path / "good.jpg"
    bad = tmp_path / "bad.jpg"
    other = tmp_path / "other.jpg"
    good.write_bytes(b"good")
    bad.write_bytes(b"bad")
    other.write_bytes(b"other")

    processed: list[str] = []

    def fake_process_clean(file: Path, output: Path | None = None):
        processed.append(file.name)
        if file.name == "bad.jpg":
            raise RuntimeError("broken")
        result = output or file.with_name(f"{file.stem}_cleaned{file.suffix}")
        result.write_bytes(file.read_bytes())
        return result, 2

    monkeypatch.setattr(cli.analyzer, "analyze", lambda path: _report(Path(path)))
    monkeypatch.setattr(cli.analyzer, "verify", lambda path: [])
    monkeypatch.setattr(cli, "_process_clean", fake_process_clean)

    result = runner.invoke(
        cli.app,
        ["batch", str(good), str(bad), str(other), "--mode", "clean", "--yes"],
    )

    assert result.exit_code == 1
    assert processed == ["good.jpg", "bad.jpg", "other.jpg"]
    assert "2 succeeded" in result.output
    assert "1 failed" in result.output


def test_batch_returns_failure_for_unverified_analysis(tmp_path, monkeypatch) -> None:
    file = tmp_path / "unverified.jpg"
    file.write_bytes(b"x")

    monkeypatch.setattr(
        cli.analyzer,
        "analyze",
        lambda path: _report(Path(path), status="unverified", error="decode failed"),
    )

    result = runner.invoke(cli.app, ["batch", str(file), "--mode", "spoof", "--yes"])

    assert result.exit_code == 1
    assert "unverified" in result.output


def test_batch_returns_failure_when_clean_leaves_residual(tmp_path, monkeypatch) -> None:
    file = tmp_path / "dirty.jpg"
    file.write_bytes(b"x")

    def fake_process_clean(source: Path, output: Path | None = None):
        result = output or source.with_name(f"{source.stem}_cleaned{source.suffix}")
        result.write_bytes(source.read_bytes())
        return result, 1

    monkeypatch.setattr(cli.analyzer, "analyze", lambda path: _report(Path(path)))
    monkeypatch.setattr(cli.analyzer, "verify", lambda path: [_report(Path(path)).fields[0]])
    monkeypatch.setattr(cli, "_process_clean", fake_process_clean)

    result = runner.invoke(cli.app, ["batch", str(file), "--mode", "clean", "--yes"])

    assert result.exit_code == 1
    assert "left" in result.output


def test_dms_output_detection() -> None:
    # Positive: names that DMS generates
    assert looks_like_dms_output(Path("photo_cleaned.jpg")) is True
    assert looks_like_dms_output(Path("photo_spoofed.heic")) is True
    assert looks_like_dms_output(Path("photo_dms.jpg")) is True
    assert looks_like_dms_output(Path("IMG_001_cleaned.HEIC")) is True
    assert looks_like_dms_output(Path("photo_cleaned_cleaned.jpg")) is True

    # Negative: user-chosen names that just happen to contain the word
    assert looks_like_dms_output(Path("my_cleaned_photo.jpg")) is False
    assert looks_like_dms_output(Path("cleaned_photo.jpg")) is False
    assert looks_like_dms_output(Path("photo.jpg")) is False
    assert looks_like_dms_output(Path("spoofed_results.pdf")) is False
    assert looks_like_dms_output(Path("vacation.heic")) is False

    # Edge: case insensitive
    assert looks_like_dms_output(Path("Photo_Cleaned.JPG")) is True
    assert looks_like_dms_output(Path("Photo_SPOOFED.heic")) is True
