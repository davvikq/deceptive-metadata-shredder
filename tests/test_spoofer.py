import os
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from dms.core.models import FileReport, MetaField
from dms.config import get_exiftool_path
from dms.core.analyzer import analyze
from dms.core.models import SpoofProfile
from dms.core import spoofer as spoofer_module
from dms.core.spoofer import (
    _existing_author_fields,
    apply_smart_spoof,
    apply_spoof,
)
from dms.interfaces.gui.app import FileSession, MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FIXTURES = Path(__file__).parent / "fixtures"


def _field(
    key: str,
    *,
    category: str,
    sensitive: bool = True,
    value: object = "value",
    exiftool_tag: str | None = None,
    is_computed: bool = False,
) -> MetaField:
    return MetaField(
        exiftool_tag=exiftool_tag or key,
        key=key,
        label=key,
        value=value,
        category=category,
        spoofable=True,
        is_sensitive=sensitive,
        is_computed=is_computed,
    )


def _report(path: Path, fields: list[MetaField]) -> FileReport:
    return FileReport(path=path, file_type=path.suffix.lstrip(".") or "jpeg", fields=fields)


@pytest.mark.skipif(not get_exiftool_path(), reason="exiftool is required for spoof tests")
def test_original_file_is_not_modified_after_spoof(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())
    before = source.read_bytes()
    report = analyze(source)

    result = apply_spoof(
        report,
        SpoofProfile(gps_mode="manual", gps_target=(48.8566, 2.3522), dates_mode="keep"),
    )

    assert result.exists()
    assert source.read_bytes() == before


@pytest.mark.skipif(not get_exiftool_path(), reason="exiftool is required for spoof tests")
def test_output_file_contains_new_coordinates(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes((FIXTURES / "test_with_gps.jpg").read_bytes())
    report = analyze(source)

    result = apply_spoof(
        report,
        SpoofProfile(gps_mode="manual", gps_target=(48.8566, 2.3522), dates_mode="keep"),
    )
    spoofed = analyze(result).by_key()

    assert abs(float(spoofed["GPSLatitude"].value) - 48.8566) < 0.01
    assert abs(float(spoofed["GPSLongitude"].value) - 2.3522) < 0.01


def test_raw_owner_and_serial_are_spoofed_when_present(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.dng"
    source.write_bytes(b"raw-source")
    captured_writes: list[dict[str, object]] = []

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        captured_writes.append(dict(writes))
        return True

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)

    report = FileReport(
        path=source,
        file_type="raw",
        fields=[
            MetaField("EXIF:OwnerName", "OwnerName", "Owner Name", "Alice", "author", True, True),
            MetaField("EXIF:SerialNumber", "SerialNumber", "Serial Number", "1234567890", "device", True, True),
            MetaField("EXIF:ImageUniqueID", "ImageUniqueID", "Image Unique ID", "abcd", "other", True, True),
        ],
    )

    result, _, _ = apply_smart_spoof(report)

    all_writes = {key: value for writes in captured_writes for key, value in writes.items()}
    assert result != source
    assert "OwnerName" in all_writes
    assert "SerialNumber" in all_writes
    assert "ImageUniqueID" in all_writes


def test_raw_original_file_is_not_modified(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.dng"
    source.write_bytes(b"raw-original")
    before = source.read_bytes()

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", lambda *args, **kwargs: True)

    report = FileReport(
        path=source,
        file_type="raw",
        fields=[
            MetaField("EXIF:SerialNumber", "SerialNumber", "Serial Number", "1234567890", "device", True, True),
        ],
    )

    result, _, _ = apply_smart_spoof(report)

    assert result.exists()
    assert source.read_bytes() == before


def test_smart_spoof_reports_missing_country_data(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module.geo_validator, "has_country_data", lambda: False)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:GPSLatitude", "GPSLatitude", "GPS Latitude", 55.75, "gps", True, True),
            MetaField("EXIF:GPSLongitude", "GPSLongitude", "GPS Longitude", 37.61, "gps", True, True),
        ],
    )

    _, _, info_codes = apply_smart_spoof(report)

    assert "smart_spoof_skip_gps_no_country_data" in info_codes


def test_smart_spoof_reports_partial_device_failure(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        if "Make" in writes and "Model" in writes:
            return False
        return True

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(
        spoofer_module,
        "_device_updates_for_make",
        lambda make, current_model=None, report=None: {
            "Make": "Samsung",
            "Model": "Galaxy S24",
            "Software": "One UI 6",
        },
    )
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("EXIF:Model", "Model", "Device Model", "iPhone 15", "device", True, True),
        ],
    )

    _, _, info_codes = apply_smart_spoof(report)

    assert "smart_spoof_partial_device_failed" in info_codes


# ──────────────────────────────────────────────────────────────
# BUG 1: Clean Residual must not delete spoofed device fields
# ──────────────────────────────────────────────────────────────

def test_clean_residual_does_not_delete_spoofed_device(tmp_path) -> None:
    """After device spoof, clean_residual must not remove device-category fields."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        original = tmp_path / "photo.jpg"
        work = tmp_path / "photo_cleaned.jpg"
        original.write_bytes(b"x")
        work.write_bytes(b"x")

        report = _report(work, [
            _field("Make", category="device", value="Apple", exiftool_tag="EXIF:Make"),
            _field("Model", category="device", value="iPhone 15", exiftool_tag="EXIF:Model"),
            _field("Software", category="device", value="17.0", exiftool_tag="EXIF:Software"),
            _field("LensModel", category="device", value="iPhone 15 back camera", exiftool_tag="EXIF:LensModel"),
            _field("SerialNumber", category="device", value="ABC123", exiftool_tag="EXIF:SerialNumber"),
            _field("HostComputer", category="device", value="iPhone 15", exiftool_tag="EXIF:HostComputer"),
            _field("CreatorTool", category="device", value="17.0", exiftool_tag="XMP:CreatorTool"),
        ])

        window.session = FileSession(
            original_path=original,
            work_path=work,
            original_report=report,
            current_report=report,
            temp_dir=tmp_path,
        )

        # Simulate device spoof: Mark Make as spoofed (expands to linked tags)
        window._record_session_changes({"Make", "Model", "Software"}, "spoofed")
        window._apply_session_states(report)

        residual = window._residual_fields(report)
        residual_keys = {field.key for field in residual}

        # No device tags should appear in residual after device spoof
        assert "Make" not in residual_keys
        assert "Model" not in residual_keys
        assert "Software" not in residual_keys
        assert "LensModel" not in residual_keys
        assert "SerialNumber" not in residual_keys
        assert "HostComputer" not in residual_keys
        assert "CreatorTool" not in residual_keys
    finally:
        window.close()


def test_clean_residual_category_protection(tmp_path) -> None:
    """Even fields not in LINKED_TAGS are protected if their category was spoofed."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        original = tmp_path / "photo.jpg"
        work = tmp_path / "photo_cleaned.jpg"
        original.write_bytes(b"x")
        work.write_bytes(b"x")

        report = _report(work, [
            _field("Make", category="device", value="Apple"),
            _field("UniqueCameraModel", category="device", value="Apple iPhone 15"),
            _field("GPSLatitude", category="gps", value="55.75"),
        ])

        window.session = FileSession(
            original_path=original,
            work_path=work,
            original_report=report,
            current_report=report,
            temp_dir=tmp_path,
        )

        window._record_session_changes({"Make"}, "spoofed")
        window._apply_session_states(report)

        residual = window._residual_fields(report)
        residual_keys = {field.key for field in residual}

        # UniqueCameraModel is in device category — should be protected
        assert "UniqueCameraModel" not in residual_keys
        # GPS should remain in residual (different category, not spoofed)
        assert "GPSLatitude" in residual_keys
    finally:
        window.close()


# ──────────────────────────────────────────────────────────────
# BUG 2: CreatorTool must be software name, not person name
# ──────────────────────────────────────────────────────────────

def test_creator_tool_excluded_from_author_fields() -> None:
    """_existing_author_fields must not match CreatorTool."""
    report = FileReport(
        path=Path("test.jpg"),
        file_type="jpeg",
        fields=[
            MetaField("XMP:CreatorTool", "CreatorTool", "Creator Tool", "Adobe Photoshop", "device", True, True),
            MetaField("XMP:Creator", "Creator", "Creator", "John Doe", "author", True, True),
            MetaField("EXIF:Artist", "Artist", "Artist", "John Doe", "author", True, True),
        ],
    )

    author_fields = _existing_author_fields(report)
    author_keys = {field.key for field in author_fields}

    assert "CreatorTool" not in author_keys
    assert "Creator" in author_keys
    assert "Artist" in author_keys


def test_creator_tool_is_software_not_name(tmp_path, monkeypatch) -> None:
    """Device spoof must set CreatorTool to software name, not a person's name."""
    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")
    captured_writes: list[dict[str, object]] = []

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        captured_writes.append(dict(writes))
        return True

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("EXIF:Model", "Model", "Device Model", "iPhone 15", "device", True, True),
            MetaField("EXIF:Software", "Software", "Software", "17.0", "device", True, True),
            MetaField("XMP:CreatorTool", "CreatorTool", "Creator Tool", "17.0", "device", True, True),
            MetaField("XMP:Creator", "Creator", "Creator", "John Doe", "author", True, True),
        ],
    )

    apply_smart_spoof(report)

    all_writes = {key: value for batch in captured_writes for key, value in batch.items()}

    # CreatorTool should NOT contain a human name
    if "CreatorTool" in all_writes:
        assert all_writes["CreatorTool"] != "John Doe"
        # It should match the Software or device name pattern
        creator_tool = str(all_writes["CreatorTool"])
        assert any(
            keyword in creator_tool
            for keyword in ["Photoshop", "GIMP", "Lightroom", "Capture", "Canon", "Nikon", "Sony", "Samsung", "Apple"]
        ) or creator_tool == all_writes.get("Software", "")


# ──────────────────────────────────────────────────────────────
# BUG 3: Device spoof writes all necessary tags
# ──────────────────────────────────────────────────────────────

def test_device_spoof_writes_creator_tool_and_xmp(tmp_path, monkeypatch) -> None:
    """Device spoof must write CreatorTool, XMP variants when they exist."""
    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")
    captured_writes: list[dict[str, object]] = []

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        captured_writes.append(dict(writes))
        return True

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("EXIF:Model", "Model", "Device Model", "iPhone 15", "device", True, True),
            MetaField("EXIF:Software", "Software", "Software", "17.0", "device", True, True),
            MetaField("EXIF:LensMake", "LensMake", "Lens Make", "Apple", "device", True, True),
            MetaField("EXIF:LensModel", "LensModel", "Lens Model", "iPhone 15 back camera", "device", True, True),
            MetaField("XMP:CreatorTool", "CreatorTool", "Creator Tool", "17.0", "device", True, True),
            MetaField("EXIF:SerialNumber", "SerialNumber", "Serial Number", "XYZ123", "device", True, True),
        ],
    )

    apply_smart_spoof(report)

    all_writes = {key: value for batch in captured_writes for key, value in batch.items()}

    # Core device tags must be written
    assert "Make" in all_writes
    assert "Model" in all_writes
    assert "Software" in all_writes
    # CreatorTool must be written during device spoof
    assert "CreatorTool" in all_writes
    # Lens tags that existed must be re-written
    assert "LensMake" in all_writes
    assert "LensModel" in all_writes
    # Serial must be replaced
    assert "SerialNumber" in all_writes


# ──────────────────────────────────────────────────────────────
# BUG 4: Face ID / Region Extensions always deleted
# ──────────────────────────────────────────────────────────────

def test_face_id_always_deleted(tmp_path, monkeypatch) -> None:
    """Region Extensions (Face ID) must be nuked via XMP block syntax;
    non-Region always-delete tags go through standard _run_exiftool_edits."""
    import subprocess as _subprocess
    from dms.core.constants import REGION_XMP_NUKE_ARGS

    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")
    captured_clears: list[list[str]] = []
    captured_subprocess_args: list[list[str]] = []

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        captured_clears.append(list(clears))
        return True

    def fake_subprocess_run(args, **kwargs):
        captured_subprocess_args.append(list(args))
        return _subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "require_exiftool", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)
    monkeypatch.setattr(spoofer_module.subprocess, "run", fake_subprocess_run)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("XMP-mwg-rs:RegionExtensionsFaceID", "RegionExtensionsFaceID", "Face ID", "abc-123", "other", True, True, is_computed=True),
            MetaField("XMP-mwg-rs:RegionExtensionsAngleInfoRoll", "RegionExtensionsAngleInfoRoll", "Angle Roll", "0.5", "other", True, True, is_computed=True),
            MetaField("XMP-mwg-rs:RegionExtensionsConfidenceLevel", "RegionExtensionsConfidenceLevel", "Confidence", "0.99", "other", True, True, is_computed=True),
            MetaField("EXIF:AccelerationVector", "AccelerationVector", "Acceleration", "0.1 0.2 9.8", "other", True, True, is_computed=True),
        ],
    )

    apply_smart_spoof(report)

    # Region tags are nuked via subprocess.run with REGION_XMP_NUKE_ARGS
    nuke_calls = [
        args for args in captured_subprocess_args
        if any(nuke_arg in args for nuke_arg in REGION_XMP_NUKE_ARGS)
    ]
    assert len(nuke_calls) >= 1, f"Expected Region nuke call, got: {captured_subprocess_args}"
    nuke_args_flat = nuke_calls[0]
    assert "-XMP:RegionInfo=" in nuke_args_flat
    assert "-XMP-mwg-rs:Regions=" in nuke_args_flat

    # Non-Region always-delete tag (AccelerationVector) goes through _run_exiftool_edits
    all_clears = [tag for batch in captured_clears for tag in batch]
    assert "EXIF:AccelerationVector" in all_clears


def test_region_area_tags_nuked_via_xmp_blocks(tmp_path, monkeypatch) -> None:
    """Region area/person tags trigger the XMP Region block nuke."""
    import subprocess as _subprocess
    from dms.core.constants import REGION_XMP_NUKE_ARGS

    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")
    captured_subprocess_args: list[list[str]] = []

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        return True

    def fake_subprocess_run(args, **kwargs):
        captured_subprocess_args.append(list(args))
        return _subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "require_exiftool", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)
    monkeypatch.setattr(spoofer_module.subprocess, "run", fake_subprocess_run)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("XMP-mwg-rs:RegionAreaH", "RegionAreaH", "Region Area H", "0.15", "other", True, True, is_computed=True),
            MetaField("XMP-mwg-rs:RegionName", "RegionName", "Region Name", "John", "other", True, True, is_computed=True),
            MetaField("XMP-mwg-rs:RegionPersonDisplayName", "RegionPersonDisplayName", "Person", "John Doe", "other", True, True, is_computed=True),
        ],
    )

    apply_smart_spoof(report)

    nuke_calls = [
        args for args in captured_subprocess_args
        if any(nuke_arg in args for nuke_arg in REGION_XMP_NUKE_ARGS)
    ]
    assert len(nuke_calls) >= 1, "Region nuke subprocess call not found"
    nuke_flat = nuke_calls[0]
    assert "-XMP:RegionInfo=" in nuke_flat
    assert "-XMP-mwg-rs:Regions=" in nuke_flat
    assert "-XMP:RegionExtensions=" in nuke_flat


def test_reports_info_code_when_region_cleanup_fails(tmp_path, monkeypatch) -> None:
    import subprocess as _subprocess

    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        return True

    def fake_subprocess_run(args, **kwargs):
        return _subprocess.CompletedProcess(args, 1, stdout="", stderr="region cleanup failed")

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "require_exiftool", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)
    monkeypatch.setattr(spoofer_module.subprocess, "run", fake_subprocess_run)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("XMP-mwg-rs:RegionName", "RegionName", "Region Name", "John", "other", True, True, is_computed=True),
        ],
    )

    _, _, info_codes = apply_smart_spoof(report)

    assert "smart_spoof_partial_region_cleanup_failed" in info_codes


def test_reports_info_code_when_non_region_cleanup_fails(tmp_path, monkeypatch) -> None:
    import subprocess as _subprocess

    source = tmp_path / "source.jpg"
    source.write_bytes(b"jpeg-data")

    def fake_run_edits(destination, clears, writes, *, soft_fail=False):
        if "EXIF:AccelerationVector" in clears:
            return False
        return True

    def fake_subprocess_run(args, **kwargs):
        return _subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(spoofer_module, "get_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "require_exiftool", lambda: "exiftool")
    monkeypatch.setattr(spoofer_module, "_run_exiftool_edits", fake_run_edits)
    monkeypatch.setattr(spoofer_module.subprocess, "run", fake_subprocess_run)

    report = FileReport(
        path=source,
        file_type="jpeg",
        fields=[
            MetaField("EXIF:Make", "Make", "Device Make", "Apple", "device", True, True),
            MetaField("EXIF:AccelerationVector", "AccelerationVector", "Acceleration", "0.1 0.2 9.8", "other", True, True, is_computed=True),
        ],
    )

    _, _, info_codes = apply_smart_spoof(report)

    assert "smart_spoof_partial_non_region_cleanup_failed" in info_codes


def test_region_tags_excluded_from_residual(tmp_path) -> None:
    """Region tags must not appear in _residual_fields (handled separately)."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        original = tmp_path / "photo.jpg"
        work = tmp_path / "photo_cleaned.jpg"
        original.write_bytes(b"x")
        work.write_bytes(b"x")

        report = _report(work, [
            _field("Make", category="device", value="Apple"),
            _field("RegionAreaH", category="other", value="0.15", exiftool_tag="XMP-mwg-rs:RegionAreaH"),
            _field("RegionName", category="other", value="John", exiftool_tag="XMP-mwg-rs:RegionName"),
            _field("RegionExtensionsFaceID", category="other", value="abc", exiftool_tag="XMP-mwg-rs:RegionExtensionsFaceID"),
        ])

        window.session = FileSession(
            original_path=original,
            work_path=work,
            original_report=report,
            current_report=report,
            temp_dir=tmp_path,
        )
        window._apply_session_states(report)

        residual = window._residual_fields(report)
        residual_keys = {field.key for field in residual}

        # Region tags should NOT appear in residual — they're auto-deleted separately
        assert "RegionAreaH" not in residual_keys
        assert "RegionName" not in residual_keys
        assert "RegionExtensionsFaceID" not in residual_keys
    finally:
        window.close()


def test_always_delete_tags_marked_as_computed() -> None:
    """Fields in ALWAYS_DELETE_TAGS must have is_computed=True in analyzer output."""
    from dms.core.analyzer import _safe_append

    fields: list[MetaField] = []
    _safe_append(fields, "XMP:RegionExtensionsFaceID", "abc-123")
    assert len(fields) == 1
    assert fields[0].is_computed is True


def test_region_prefix_marked_as_computed() -> None:
    """Region-prefixed fields not in ALWAYS_DELETE_TAGS are also is_computed=True."""
    from dms.core.analyzer import _safe_append

    fields: list[MetaField] = []
    _safe_append(fields, "XMP-mwg-rs:RegionAreaH", "0.15")
    assert len(fields) == 1
    assert fields[0].is_computed is True


# ──────────────────────────────────────────────────────────────
# BUG 5: Batch _clean_residual must protect spoofed device tags
# ──────────────────────────────────────────────────────────────

def test_batch_clean_residual_protects_spoofed_device_category(tmp_path) -> None:
    """BatchWorker._clean_residual must not list device fields when device category is spoofed."""
    import copy
    from dms.interfaces.gui.app import (
        BatchWorker,
        _populate_session_keys,
        _apply_states_to_report,
    )

    original = tmp_path / "photo.jpg"
    work = tmp_path / "photo_cleaned.jpg"
    original.write_bytes(b"x")
    work.write_bytes(b"x")

    original_report = _report(work, [
        _field("Make", category="device", value="Apple", exiftool_tag="EXIF:Make"),
        _field("Model", category="device", value="iPhone 15", exiftool_tag="EXIF:Model"),
        _field("Software", category="device", value="17.0", exiftool_tag="EXIF:Software"),
        _field("LensModel", category="device", value="iPhone 15 cam", exiftool_tag="EXIF:LensModel"),
        _field("CreatorTool", category="device", value="17.0", exiftool_tag="XMP:CreatorTool"),
        _field("GPSLatitude", category="gps", value="55.75", exiftool_tag="EXIF:GPSLatitude"),
    ])

    spoofed_report = _report(work, [
        _field("Make", category="device", value="Samsung", exiftool_tag="EXIF:Make"),
        _field("Model", category="device", value="Galaxy S24", exiftool_tag="EXIF:Model"),
        _field("Software", category="device", value="One UI 6", exiftool_tag="EXIF:Software"),
        _field("LensModel", category="device", value="Samsung cam", exiftool_tag="EXIF:LensModel"),
        _field("CreatorTool", category="device", value="One UI 6", exiftool_tag="XMP:CreatorTool"),
        _field("GPSLatitude", category="gps", value="55.75", exiftool_tag="EXIF:GPSLatitude"),
    ])

    session = FileSession(
        original_path=original,
        work_path=work,
        original_report=copy.deepcopy(original_report),
        current_report=spoofed_report,
        temp_dir=tmp_path,
    )

    _populate_session_keys(session)
    _apply_states_to_report(session)

    assert session.spoofed_keys, "spoofed_keys should be populated after _populate_session_keys"

    worker = BatchWorker([], "spoof_clean", "en")

    residual_fields: list[MetaField] = []
    for field in spoofed_report.fields:
        if not field.is_sensitive or field.is_computed:
            continue
        if field.status in {"spoofed", "removed", "clean"}:
            continue
        from dms.interfaces.gui.app import _field_aliases, _is_always_delete_field, _SYSTEM_DATE_KEYS
        if _is_always_delete_field(field):
            continue
        if field.key in _SYSTEM_DATE_KEYS:
            continue
        aliases = _field_aliases(field)
        if aliases & session.spoofed_keys:
            continue
        spoofed_categories: set[str] = set()
        for f in spoofed_report.fields:
            fa = _field_aliases(f)
            if f.status == "spoofed" or fa & session.spoofed_keys:
                spoofed_categories.add(f.category)
        if field.category in spoofed_categories:
            continue
        residual_fields.append(field)

    residual_keys = {f.key for f in residual_fields}

    assert "Make" not in residual_keys, "Make should be protected (device category spoofed)"
    assert "Model" not in residual_keys, "Model should be protected"
    assert "Software" not in residual_keys, "Software should be protected"
    assert "LensModel" not in residual_keys, "LensModel should be protected"
    assert "CreatorTool" not in residual_keys, "CreatorTool should be protected"
    assert "GPSLatitude" in residual_keys, "GPSLatitude should remain residual (not spoofed)"
