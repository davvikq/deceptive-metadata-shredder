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


def test_spoof_invalid_device_and_gps_show_diagnostic_errors(tmp_path) -> None:
    source = _copy_fixture(tmp_path)

    bad_device = runner.invoke(
        cli.app,
        ["spoof", str(source), "--device", "nonexistent_device", "--yes"],
    )
    assert bad_device.exit_code != 0
    assert "Unknown device id: nonexistent_device" in bad_device.output
    assert "dms devices" in bad_device.output
    assert "Something went wrong" not in bad_device.output

    bad_gps = runner.invoke(
        cli.app,
        ["spoof", str(source), "--gps", "1,2,3", "--yes"],
    )
    assert bad_gps.exit_code != 0
    assert "Invalid GPS coordinates" in bad_gps.output
    assert "Something went wrong" not in bad_gps.output


def test_cli_devices_lists_device_ids() -> None:
    table_result = runner.invoke(cli.app, ["devices"])
    assert table_result.exit_code == 0
    assert "device(s) available" in table_result.output

    json_result = runner.invoke(cli.app, ["devices", "--format", "json"])
    assert json_result.exit_code == 0
    devices_payload = json.loads(json_result.output)
    assert isinstance(devices_payload, list)
    assert len(devices_payload) > 0
    assert {"id", "make", "model"}.issubset(devices_payload[0])


def test_cli_clean_pdf_strip_flags(tmp_path) -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Text

    source = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_annotation(page_number=0, annotation=Text(rect=(10, 10, 30, 30), text="PII_IN_ANNOTATION"))
    writer.add_attachment(filename="secret.txt", data=b"attachment-secret")
    writer.write(source)

    result = runner.invoke(
        cli.app,
        ["clean", str(source), "--strip-annotations", "--strip-attachments", "--yes"],
    )

    assert result.exit_code == 0
    cleaned = source.with_name(f"{source.stem}_cleaned{source.suffix}")
    assert b"PII_IN_ANNOTATION" not in cleaned.read_bytes()
    assert PdfReader(cleaned).attachments == {}


def test_clean_does_not_print_cleaned_when_verification_fails(tmp_path, monkeypatch) -> None:
    source = _copy_fixture(tmp_path)
    residual = MetaField(
        exiftool_tag="QuickTime:CreateDate",
        key="CreateDate",
        label="Create Date",
        value="2024:01:01 00:00:00",
        category="dates",
        spoofable=True,
        is_sensitive=True,
    )
    monkeypatch.setattr(cli.analyzer, "verify", lambda _path: [residual])

    result = runner.invoke(cli.app, ["clean", str(source), "--yes"])

    assert result.exit_code == 1
    assert "✓ Cleaned:" not in result.output
    assert "Verification:" in result.output


def test_report_diff_does_not_mask_unmodified_group_variant() -> None:
    from dms.core.models import FileReport

    before = FileReport(
        path=Path("photo.jpg"),
        file_type="jpeg",
        fields=[
            MetaField("IFD0:Software", "Software", "Software", "OldApp", "device", True, True),
            MetaField("XMP-tiff:Software", "Software", "Software", "OldApp", "device", True, True),
        ],
    )
    after = FileReport(
        path=Path("photo_spoofed.jpg"),
        file_type="jpeg",
        fields=[
            MetaField("IFD0:Software", "Software", "Software", "NewApp", "device", True, True),
            MetaField("XMP-tiff:Software", "Software", "Software", "OldApp", "device", True, True),
        ],
    )

    changed, removed = cli._report_diff(before, after)
    cli._apply_cli_statuses(after, spoofed_keys=changed, removed_keys=removed)

    assert changed == {"IFD0:Software"}
    assert after.fields[0].status == "spoofed"
    assert after.fields[1].status == "risk"
    assert cli._risk_count(after) == 1
    assert [f.exiftool_tag for f in cli._residual_fields(after, changed)] == ["XMP-tiff:Software"]


def test_preview_spoof_plan_matches_actual_spoofer_conditions() -> None:
    from dms.core.models import FileReport, SpoofProfile

    report = FileReport(
        path=Path("doc.pdf"),
        file_type="pdf",
        fields=[
            MetaField("PDF:Producer", "Producer", "Producer", "pypdf", "author", True, True),
            MetaField("System:FileModifyDate", "FileModifyDate", "File Modified", "2024:01:01 00:00:00", "dates", True, True),
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
        ],
    )

    _, changes = cli._preview_spoof_plan(report, SpoofProfile(), smart=True)

    assert "author" not in changes
    assert "dates" not in changes
    assert "device" in changes


def test_cli_spoof_author_remove_clears_author_tags(tmp_path) -> None:
    import subprocess
    from dms.config import get_exiftool_path

    exiftool = get_exiftool_path()
    if not exiftool:
        return
    source = _copy_fixture(tmp_path)
    subprocess.run(
        [exiftool, "-overwrite_original", "-EXIF:Artist=Alice", "-XMP-dc:Creator=Alice", str(source)],
        check=True,
        capture_output=True,
    )

    result = runner.invoke(
        cli.app,
        ["spoof", str(source), "--gps", "remove", "--dates", "keep", "--author", "REMOVE", "--yes"],
    )

    assert result.exit_code == 0
    assert "Note:" in result.output
    fields = analyze(source.with_name(f"{source.stem}_spoofed{source.suffix}")).by_key()
    assert "Artist" not in fields
    assert "Creator" not in fields


def test_expand_batch_inputs_supports_absolute_glob(tmp_path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    ignored = tmp_path / "c.png"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    ignored.write_bytes(b"c")

    expanded = cli._expand_batch_inputs([Path(str(tmp_path / "*.jpg"))])

    assert expanded == [first, second]


def test_remove_residual_fields_uses_minor_flag_strips_signature_and_restores_fs_date(tmp_path, monkeypatch) -> None:
    import subprocess
    from datetime import datetime

    target = tmp_path / "photo.jpg"
    target.write_bytes(b"x")
    calls: list[list[str]] = []
    sig_calls: list[Path] = []
    fs_calls: list[tuple[Path, datetime]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(cli, "require_exiftool", lambda: "exiftool")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "remove_exiftool_signature", lambda p, _et: sig_calls.append(p))
    monkeypatch.setattr(cli, "set_filesystem_dates", lambda p, dt: fs_calls.append((p, dt)))

    anchor = datetime(2022, 6, 15, 12, 0, 0)
    field = MetaField("XMP:Rights", "Rights", "Rights", "val", "other", True, True)
    removed = cli._remove_residual_fields(target, [field], fs_date=anchor)

    assert removed == 1
    assert "-m" in calls[0]
    assert sig_calls == [target]
    assert fs_calls == [(target, anchor)]


def test_batch_and_watch_reject_invalid_mode(tmp_path) -> None:
    photo = _copy_fixture(tmp_path)

    batch_result = runner.invoke(cli.app, ["batch", str(photo), "--mode", "spoof_clean", "--yes"])
    assert batch_result.exit_code != 0
    assert "Invalid mode" in batch_result.output

    watch_result = runner.invoke(cli.app, ["watch", str(tmp_path), "--mode", "invalid_mode"])
    assert watch_result.exit_code != 0
    assert "Invalid mode" in watch_result.output


def test_spoof_raw_asks_proceed_only_once(tmp_path, monkeypatch) -> None:
    from dms.core.models import FileReport

    raw_file = tmp_path / "shot.dng"
    raw_file.write_bytes(b"raw")
    report = FileReport(
        path=raw_file,
        file_type="raw",
        fields=[MetaField("EXIF:Make", "Make", "Make", "Canon", "device", True, True)],
    )
    monkeypatch.setattr(cli.analyzer, "analyze", lambda _p: report)

    result = runner.invoke(cli.app, ["spoof", str(raw_file)], input="n\n")

    assert result.output.count("Proceed?") == 1
    assert result.exit_code == 0