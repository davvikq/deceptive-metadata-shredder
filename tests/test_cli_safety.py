import json
from pathlib import Path

from typer.testing import CliRunner

from dms.core.models import MetaField
from dms.interfaces import cli
from dms.core.analyzer import analyze


FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _copy_fixture(tmp_path: Path, name: str = "photo.jpg") -> Path:
    target = tmp_path / name
    target.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())
    return target


def test_spoof_refuses_to_overwrite_source(tmp_path) -> None:
    source = _copy_fixture(tmp_path)
    before = source.read_bytes()

    result = runner.invoke(
        cli.app,
        ["spoof", str(source), "-o", str(source), "--gps", "10,20", "--dates", "keep", "--yes"],
    )

    assert result.exit_code == 1
    assert "Output path must differ" in result.output
    assert source.read_bytes() == before


def test_clean_refuses_to_overwrite_source(tmp_path) -> None:
    source = _copy_fixture(tmp_path)
    before = source.read_bytes()

    result = runner.invoke(cli.app, ["clean", str(source), "-o", str(source), "--yes"])

    assert result.exit_code == 1
    assert "Output path must differ" in result.output
    assert source.read_bytes() == before


def test_clean_does_not_clobber_existing_output_without_confirmation(tmp_path) -> None:
    source = _copy_fixture(tmp_path)
    target = source.with_name(f"{source.stem}_cleaned{source.suffix}")
    target.write_text("PRECIOUS_OLD_OUTPUT", encoding="utf-8")

    result = runner.invoke(cli.app, ["clean", str(source)], input="n\n")

    assert result.exit_code != 0
    assert target.read_text(encoding="utf-8") == "PRECIOUS_OLD_OUTPUT"


def test_spoof_does_not_clobber_previous_cleaned_file(tmp_path) -> None:
    source = _copy_fixture(tmp_path, "photo2.jpg")
    cleaned = source.with_name(f"{source.stem}_cleaned{source.suffix}")
    cleaned.write_text("PRECIOUS_OLD_OUTPUT", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["spoof", str(source), "--gps", "10,20", "--dates", "keep", "--yes"],
    )

    assert result.exit_code == 0
    assert cleaned.read_text(encoding="utf-8") == "PRECIOUS_OLD_OUTPUT"
    assert source.with_name(f"{source.stem}_spoofed{source.suffix}").exists()


def test_dates_keep_is_not_reported_as_a_device_or_date_change(tmp_path) -> None:
    source = _copy_fixture(tmp_path)

    result = runner.invoke(
        cli.app,
        ["spoof", str(source), "--gps", "remove", "--dates", "keep", "--yes"],
    )

    assert result.exit_code == 0
    assert "Device Model" not in result.output
    assert "Create Date" not in result.output
    assert "Risk reduced:" in result.output
    final_risk = int(result.output.rsplit("→", 1)[1].split("fields", 1)[0].strip())
    assert final_risk > 0

    fields = analyze(source.with_name(f"{source.stem}_spoofed{source.suffix}")).by_key()
    assert fields["Make"].value == "Apple"
    assert "GPSLatitude" not in fields


def test_clean_returns_nonzero_when_verification_fails(tmp_path, monkeypatch) -> None:
    source = _copy_fixture(tmp_path)
    residual = MetaField(
        exiftool_tag="EXIF:Artist",
        key="Artist",
        label="Artist",
        value="Alice",
        category="author",
        spoofable=True,
        is_sensitive=True,
    )

    monkeypatch.setattr(cli.analyzer, "verify", lambda path: [residual])

    result = runner.invoke(cli.app, ["clean", str(source), "--yes"])

    assert result.exit_code == 1
    assert "Verification" in result.output


def test_analyze_json_reports_status(tmp_path) -> None:
    source = _copy_fixture(tmp_path)

    result = runner.invoke(cli.app, ["analyze", str(source), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "dirty"
    assert payload["analysis_status"] == "ok"


def test_residual_cleanup_removes_all_group_variants(tmp_path) -> None:
    from dms.config import get_exiftool_path
    import subprocess

    exiftool = get_exiftool_path()
    if not exiftool:
        return
    source = _copy_fixture(tmp_path)
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

    result = runner.invoke(
        cli.app,
        ["spoof", str(source), "--gps", "remove", "--dates", "keep", "--residual", "--yes"],
    )

    assert result.exit_code == 0
    spoofed = source.with_name(f"{source.stem}_spoofed{source.suffix}")
    software = {
        field.exiftool_tag
        for field in analyze(spoofed).fields
        if field.key == "Software"
    }
    assert software == set()