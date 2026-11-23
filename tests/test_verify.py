from pathlib import Path

import pytest
from typer.testing import CliRunner

from dms.core import analyzer as analyzer_module
from dms.core.analyzer import residual_sensitive_fields, verify
from dms.core.models import FileReport, MetaField
from dms.core.sanitizer import remove_all
from dms.interfaces import cli

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _field(key: str, category: str, *, sensitive: bool = True, computed: bool = False) -> MetaField:
    return MetaField(
        exiftool_tag=f"EXIF:{key}",
        key=key,
        label=key,
        value="v",
        category=category,
        spoofable=True,
        is_sensitive=sensitive,
        is_computed=computed,
    )


def test_residual_excludes_filesystem_dates_and_computed() -> None:
    report = FileReport(
        path=Path("x.jpg"),
        file_type="jpeg",
        fields=[
            _field("GPSLatitude", "gps"),
            _field("FileModifyDate", "dates"),
            _field("RegionName", "other", computed=True),
            _field("ImageWidth", "other", sensitive=False),
        ],
    )

    assert {field.key for field in residual_sensitive_fields(report)} == {"GPSLatitude"}


def test_verify_flags_sensitive_source_file() -> None:
    residual = verify(FIXTURES / "test_with_gps.jpg")

    assert "GPSLatitude" in {field.key for field in residual}


def test_verify_passes_after_clean(tmp_path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())

    cleaned = remove_all(source)

    assert verify(cleaned) == []


def test_cli_verify_exit_codes(tmp_path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())

    dirty = runner.invoke(cli.app, ["verify", str(source)])
    assert dirty.exit_code == 1

    cleaned = remove_all(source)
    clean = runner.invoke(cli.app, ["verify", str(cleaned)])
    assert clean.exit_code == 0


def test_verify_never_reports_unreadable_file_as_clean(monkeypatch) -> None:
    def broken_analyze(path: Path) -> FileReport:
        return FileReport(
            path=Path(path),
            file_type="jpeg",
            fields=[],
            analysis_status="partial",
            analysis_error="exiftool returned no metadata output.",
        )

    monkeypatch.setattr(analyzer_module, "analyze", broken_analyze)

    with pytest.raises(analyzer_module.MetadataAnalysisError, match="no metadata output"):
        verify(Path("unreadable.jpg"))


def test_cli_verify_and_analyze_fail_on_unverified_file(tmp_path, monkeypatch) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"x")

    def broken_analyze(path: Path) -> FileReport:
        return FileReport(
            path=Path(path),
            file_type="jpeg",
            fields=[],
            analysis_status="unverified",
            analysis_error="metadata decoding failed",
        )

    monkeypatch.setattr(cli.analyzer, "analyze", broken_analyze)

    verify_result = runner.invoke(cli.app, ["verify", str(source)])
    assert verify_result.exit_code == 1
    assert "Verification unavailable" in verify_result.output

    analyze_result = runner.invoke(cli.app, ["analyze", str(source)])
    assert analyze_result.exit_code == 1
    assert "Analysis incomplete" in analyze_result.output
