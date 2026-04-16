"""Metadata spoofing logic."""

from __future__ import annotations

import logging
import random
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from docx import Document

from dms.config import get_exiftool_path, require_exiftool
from dms.core import geo_validator
from dms.core.constants import (
    ALWAYS_DELETE_PREFIXES,
    ALWAYS_DELETE_TAGS,
    DATE_FIELD_KEYS,
    DATE_TAGS_TO_SPOOF,
    DEVICE_TAGS_TO_CLEAR,
    GPS_TAGS_TO_SPOOF,
    OFFSET_TAGS,
    REGION_XMP_NUKE_ARGS,
    SUBSEC_TAGS,
    TIMEZONE_OFFSETS,
)
from dms.core.device_db import get_all_devices, get_models_by_make, get_random_device
from dms.core.models import FileReport, MetaField, SpoofProfile, parse_metadata_datetime
from dms.core.sanitizer import repack_docx_zip_dates, resolve_spoof_destination, run_atomic_file_update
from dms.core.utils import get_subprocess_flags, remove_exiftool_signature

def _is_always_delete_field(field: "MetaField") -> bool:
    normalized = field.key.split(":")[-1].split(".")[-1]
    if normalized in ALWAYS_DELETE_TAGS:
        return True
    for prefix in ALWAYS_DELETE_PREFIXES:
        if normalized.startswith(prefix):
            return True
    return False


def _is_region_field(field: "MetaField") -> bool:
    normalized = field.key.split(":")[-1].split(".")[-1]
    for prefix in ALWAYS_DELETE_PREFIXES:
        if normalized.startswith(prefix):
            return True
    return False


def _nuke_always_delete_tags(destination: Path, file_report: "FileReport") -> tuple[bool, bool]:
    # Region XMP: nested structs need REGION_XMP_NUKE_ARGS; other always-delete tags use -=.
    always_delete_fields = [
        f for f in file_report.fields if _is_always_delete_field(f)
    ]
    if not always_delete_fields:
        return True, True

    has_region = any(_is_region_field(f) for f in always_delete_fields)
    non_region = [f for f in always_delete_fields if not _is_region_field(f)]

    exiftool_path = require_exiftool()
    region_ok = True
    non_region_ok = True

    if has_region:
        args = [exiftool_path, "-overwrite_original", "-m"]
        args.extend(REGION_XMP_NUKE_ARGS)
        args.append(str(destination))
        logging.debug("Nuking Region XMP blocks: %s", REGION_XMP_NUKE_ARGS)
        result = subprocess.run(
            args, capture_output=True, text=True,
            creationflags=get_subprocess_flags(),
        )
        if result.returncode != 0:
            region_ok = False
            logging.error(
                "Region cleanup failed: returncode=%s stderr=%s",
                result.returncode,
                (result.stderr or "").strip(),
            )

    if non_region:
        tags = [f.exiftool_tag for f in non_region]
        logging.debug("Deleting non-Region always-delete tags: %s", tags)
        non_region_ok = _run_exiftool_edits(destination, tags, {}, soft_fail=True)

    return region_ok, non_region_ok


WRITABLE_DATE_FORMATS = {
    "jpeg": ["EXIF:DateTimeOriginal", "EXIF:CreateDate", "EXIF:ModifyDate"],
    "jpg": ["EXIF:DateTimeOriginal", "EXIF:CreateDate", "EXIF:ModifyDate"],
    "heic": ["EXIF:DateTimeOriginal", "EXIF:CreateDate", "EXIF:ModifyDate", "XMP:DateCreated"],
    "heif": ["EXIF:DateTimeOriginal", "EXIF:CreateDate", "EXIF:ModifyDate", "XMP:DateCreated"],
    "pdf": ["XMP:CreateDate", "XMP:ModifyDate"],
    "docx": ["Created", "Modified"],
    "mp4": ["QuickTime:CreateDate", "QuickTime:ModifyDate"],
    "mov": ["QuickTime:CreateDate", "QuickTime:ModifyDate"],
}
AUTHOR_TAGS = ["author", "artist", "xmp:creator", "dc:creator", "lastmodifiedby"]
_AUTHOR_EXCLUSIONS = {"creatortool"}  # e.g. CreatorTool — not a person field


def _get_field_value(report: FileReport, key: str) -> object | None:
    for field in report.fields:
        if field.key == key or field.key.split(":")[-1] == key or field.key.split(".")[-1] == key:
            return field.value
    return None


def _field_exists(report: FileReport, needle: str) -> bool:
    return _find_field(report, needle) is not None


def _find_gps_field(report: FileReport) -> MetaField | None:
    return next(
        (
            field
            for field in report.fields
            if ("gps" in field.key.lower() or "geolocation" in field.key.lower()) and field.value not in (None, "", [])
        ),
        None,
    )


def _find_field(report: FileReport, needle: str) -> MetaField | None:
    lowered = needle.lower()
    exact = next(
        (
            field
            for field in report.fields
            if field.key.lower() == lowered
            or field.key.split(":")[-1].lower() == lowered
            or field.key.split(".")[-1].split(":")[-1].lower() == lowered
        ),
        None,
    )
    if exact is not None:
        return exact
    return next((field for field in report.fields if lowered in field.key.lower()), None)


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y:%m:%d %H:%M:%S")


def _format_for_tag(tag: str, value: datetime) -> str:
    if tag in {"DateCreated", "GPSDateStamp"}:
        return value.strftime("%Y:%m:%d")
    if tag in {"TimeCreated", "GPSTimeStamp"}:
        return value.strftime("%H:%M:%S")
    if tag in {"SubSecTimeOriginal", "SubSecTimeDigitized"}:
        return "000"
    return _format_datetime(value)


def get_writable_date_tags(file_type: str) -> list[str]:
    """Return canonical writable date tags for the current file type."""

    normalized = file_type.lower()
    return WRITABLE_DATE_FORMATS.get(normalized, [])


def _get_date_write_tags(file_type: str) -> list[str]:
    normalized = file_type.lower()
    if normalized in ("heic", "heif"):
        return [
            "EXIF:DateTimeOriginal",
            "EXIF:CreateDate",
            "EXIF:ModifyDate",
            "XMP:DateCreated",
            "XMP:CreateDate",
            "XMP:ModifyDate",
        ]
    if normalized in ("jpeg", "jpg", "png", "tiff", "mp4", "mov"):
        return [
            "EXIF:DateTimeOriginal",
            "EXIF:CreateDate",
            "EXIF:ModifyDate",
            "XMP:DateTimeOriginal",
            "XMP:CreateDate",
            "XMP:ModifyDate",
            "QuickTime:CreateDate",
            "QuickTime:ModifyDate",
        ]
    if normalized == "pdf":
        return [
            "XMP:CreateDate",
            "XMP:ModifyDate",
            "XMP:MetadataDate",
            "PDF:CreateDate",
            "PDF:ModifyDate",
        ]
    return [
        "XMP:CreateDate",
        "XMP:ModifyDate",
        "EXIF:DateTimeOriginal",
    ]


def _format_grouped_date(tag: str, value: datetime) -> str:
    if tag.startswith("XMP:") or tag.startswith("PDF:"):
        return value.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return value.strftime("%Y:%m:%d %H:%M:%S")


def _datetime_to_zip_time(dt: datetime) -> tuple[int, int, int, int, int, int]:
    return (max(dt.year, 1980), dt.month, dt.day, dt.hour, dt.minute, dt.second)


def _apply_docx_dates(destination: Path, value: datetime, remove: bool = False) -> bool:
    document = Document(str(destination))
    if remove:
        fallback = datetime(1970, 1, 1, 0, 0, 0)
        try:
            document.core_properties.created = None
            document.core_properties.modified = None
        except Exception:
            document.core_properties.created = fallback
            document.core_properties.modified = fallback
    else:
        document.core_properties.created = value
        document.core_properties.modified = value
    document.save(str(destination))
    zip_dt = _datetime_to_zip_time(value if not remove else datetime(1980, 1, 1))
    repack_docx_zip_dates(destination, zip_dt)
    return True


def _clear_offset_tags(destination: Path) -> None:
    exiftool_path = require_exiftool()
    subprocess.run(
        [
            exiftool_path,
            "-m",
            "-overwrite_original",
            "-OffsetTime=",
            "-OffsetTimeOriginal=",
            "-OffsetTimeDigitized=",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=get_subprocess_flags(),
    )


def _apply_heic_dates(destination: Path, report: FileReport, value: datetime | None, remove: bool = False) -> bool:
    # HEIC: dates in EXIF+XMP (EXIF-style string), not QuickTime; Composite is derived.
    exiftool_path = require_exiftool()
    date_str = _format_datetime(value or datetime.now(timezone.utc).replace(tzinfo=None))

    heic_date_tags = [
        "EXIF:DateTimeOriginal",
        "EXIF:CreateDate",
        "EXIF:ModifyDate",
        "XMP:DateCreated",
        "XMP:CreateDate",
        "XMP:ModifyDate",
    ]

    args = [exiftool_path, "-overwrite_original", "-m"]
    for tag in heic_date_tags:
        args.append(f"-{tag}=" if remove else f"-{tag}={date_str}")

    fake_offset = random.choice(TIMEZONE_OFFSETS)
    fake_subsec = str(random.randint(0, 999)).zfill(3)
    for tag in OFFSET_TAGS:
        if _field_exists(report, tag.lower()):
            args.append(f"-{tag}=" if remove else f"-{tag}={fake_offset}")
    for tag in SUBSEC_TAGS:
        if _field_exists(report, tag.lower()):
            args.append(f"-{tag}=" if remove else f"-{tag}={fake_subsec}")

    args.append(str(destination))
    result = subprocess.run(args, capture_output=True, text=True, creationflags=get_subprocess_flags())
    if "0 image files updated" in (result.stdout or ""):
        logging.error("HEIC date write: 0 files updated, stderr=%s", (result.stderr or "").strip())
        raise PermissionError("No date fields could be written")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if not all(
            line.strip().startswith("Warning:") or line.strip().startswith("Error: [minor]") or line.strip() == "Nothing to do." or not line.strip()
            for line in stderr.splitlines()
        ):
            logging.error("HEIC date write failed: %s", stderr)
            return False

    _clear_offset_tags(destination)
    return True


def _apply_dates_to_destination(destination: Path, report: FileReport, value: datetime | None, remove: bool = False) -> bool:
    file_type = report.file_type.lower()
    if file_type == "docx":
        return _apply_docx_dates(destination, value or datetime(1970, 1, 1), remove=remove)

    if file_type in ("heic", "heif"):
        return _apply_heic_dates(destination, report, value, remove=remove)

    exiftool_path = require_exiftool()
    args = [exiftool_path, "-m", "-overwrite_original"]
    write_tags = _get_date_write_tags(file_type)
    for tag in write_tags:
        args.append(f"-{tag}=" if remove else f"-{tag}={_format_grouped_date(tag, value or datetime.now(timezone.utc).replace(tzinfo=None))}")

    fake_offset = random.choice(TIMEZONE_OFFSETS)
    fake_subsec = str(random.randint(0, 999)).zfill(3)
    for tag in OFFSET_TAGS:
        if _field_exists(report, tag.lower()):
            args.append(f"-{tag}=" if remove else f"-{tag}={fake_offset}")
    for tag in SUBSEC_TAGS:
        if _field_exists(report, tag.lower()):
            args.append(f"-{tag}=" if remove else f"-{tag}={fake_subsec}")

    args.append(str(destination))
    result = subprocess.run(args, capture_output=True, text=True, creationflags=get_subprocess_flags())
    if "0 image files updated" in (result.stdout or ""):
        raise PermissionError("No date fields could be written")
    if result.returncode != 0:
        logging.error("date write failed: %s", (result.stderr or "").strip())
        return False

    _clear_offset_tags(destination)
    return True


def _resolve_date_value(report: FileReport, payload: dict[str, object] | None = None) -> tuple[datetime | None, bool]:
    remove = bool(payload and payload.get("__dms_dates_remove__"))
    if remove:
        return None, True

    if payload and payload.get("__dms_date_value__"):
        parsed = parse_metadata_datetime(payload["__dms_date_value__"])
        if parsed is not None:
            return parsed, False

    present = [
        parse_metadata_datetime(field.value)
        for field in report.fields
        if field.key in DATE_FIELD_KEYS and parse_metadata_datetime(field.value) is not None
    ]
    return (min(present) if present else datetime.now(timezone.utc).replace(tzinfo=None)), False


def _run_exiftool_edits(destination: Path, clears: list[str], writes: dict[str, object], *, soft_fail: bool = False) -> bool:
    if not clears and not writes:
        return True
    exiftool_path = require_exiftool()
    args = [exiftool_path]
    args.extend(f"-{tag}=" for tag in clears)
    for tag, value in writes.items():
        args.append(f"-{tag}={value}")
    args.extend(["-overwrite_original", str(destination)])
    result = subprocess.run(args, capture_output=True, text=True, creationflags=get_subprocess_flags())
    if result.returncode != 0:
        message = result.stderr.strip() or "Failed to apply metadata update."
        logging.error("exiftool failed: %s", message)
        if soft_fail:
            return False
        raise RuntimeError(message)
    return True


def _raw_sensitive_updates(report: FileReport) -> dict[str, str]:
    updates: dict[str, str] = {}
    if _field_exists(report, "OwnerName"):
        try:
            from faker import Faker

            updates["OwnerName"] = Faker().name()
        except Exception:  # Faker optional in minimal installs
            updates["OwnerName"] = "John Smith"
    if _field_exists(report, "SerialNumber"):
        updates["SerialNumber"] = "".join(random.choices("0123456789", k=10))
    if _field_exists(report, "CameraSerialNumber"):
        updates["CameraSerialNumber"] = "".join(random.choices("0123456789", k=10))
    if _field_exists(report, "ImageUniqueID"):
        updates["ImageUniqueID"] = "".join(random.choices("0123456789abcdef", k=32))
    return updates


def _build_date_updates(report: FileReport, profile: SpoofProfile) -> dict[str, str]:
    updates: dict[str, str] = {}
    if profile.dates_mode == "keep":
        return updates
    existing_date_keys = {field.key for field in report.fields if field.category == "dates" or field.key in DATE_FIELD_KEYS}
    relevant_tags = [key for key in DATE_TAGS_TO_SPOOF if key in existing_date_keys or _field_exists(report, key.lower())]

    if profile.dates_mode == "remove":
        return {key: "" for key in relevant_tags}

    present = [
        parse_metadata_datetime(field.value)
        for field in report.fields
        if field.key in DATE_FIELD_KEYS and parse_metadata_datetime(field.value) is not None
    ]
    base_date = min(present) if present else datetime.now(timezone.utc).replace(tzinfo=None)
    if profile.dates_mode == "random":
        anchor = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=random.randint(30, 2000))
        for key in relevant_tags:
            updates[key] = _format_for_tag(key, anchor)
        fake_offset = random.choice(TIMEZONE_OFFSETS)
        fake_subsec = str(random.randint(0, 999)).zfill(3)
        for tag in OFFSET_TAGS:
            if _field_exists(report, tag.lower()):
                updates[tag] = fake_offset
        for tag in SUBSEC_TAGS:
            if _field_exists(report, tag.lower()):
                updates[tag] = fake_subsec
        return updates

    anchor = base_date + timedelta(days=profile.dates_shift_days)
    for key in relevant_tags:
        updates[key] = _format_for_tag(key, anchor)
    fake_offset = random.choice(TIMEZONE_OFFSETS)
    fake_subsec = str(random.randint(0, 999)).zfill(3)
    for tag in OFFSET_TAGS:
        if _field_exists(report, tag.lower()):
            updates[tag] = fake_offset
    for tag in SUBSEC_TAGS:
        if _field_exists(report, tag.lower()):
            updates[tag] = fake_subsec
    return updates


def _resolve_gps_target(report: FileReport, profile: SpoofProfile) -> tuple[float, float] | None:
    gps_field = _find_gps_field(report)
    if gps_field is None:
        return None
    if profile.gps_mode == "remove":
        return None
    if profile.gps_mode == "manual" and profile.gps_target:
        return profile.gps_target
    if profile.gps_mode == "smart":
        lat = _get_field_value(report, "GPSLatitude")
        lon = _get_field_value(report, "GPSLongitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return geo_validator.smart_spoof(float(lat), float(lon))
        return geo_validator.smart_spoof(*geo_validator.NEUTRAL_WATERS)
    return profile.gps_target


_CORE_DEVICE_TAGS: frozenset[str] = frozenset({"Make", "Model", "Software"})


def _filter_device_overrides(overrides: dict[str, object], report: FileReport | None) -> dict[str, object]:
    # Make/Model/Software always written; other exif_overrides only if tag existed — avoids new fingerprints.
    if report is None:
        return dict(overrides)
    result: dict[str, object] = {}
    for tag, value in overrides.items():
        normalized = tag.split(":")[-1].split(".")[-1]
        if normalized in _CORE_DEVICE_TAGS or _field_exists(report, normalized):
            result[tag] = value
    return result


def _build_full_device_tags(device: "Device", report: FileReport | None) -> dict[str, object]:
    from dms.core.models import Device  # noqa: F811

    software_value = device.software or f"{device.make} {device.model}"
    lens_model = device.exif_overrides.get("LensModel", f"{device.make} Standard Lens")
    lens_info = device.exif_overrides.get("LensInfo", lens_model)

    updates: dict[str, object] = {
        "Make": device.make,
        "Model": device.model,
        "Software": software_value,
        "CreatorTool": software_value,
    }

    if report is not None:
        if _field_exists(report, "LensMake"):
            updates["LensMake"] = device.make
        if _field_exists(report, "LensModel"):
            updates["LensModel"] = lens_model
        if _field_exists(report, "LensID"):
            updates["LensID"] = lens_model
        if _field_exists(report, "LensInfo"):
            updates["LensInfo"] = lens_info
        if _field_exists(report, "XMP:Make") or _field_exists(report, "XMP-tiff:Make"):
            updates["XMP:Make"] = device.make
        if _field_exists(report, "XMP:Model") or _field_exists(report, "XMP-tiff:Model"):
            updates["XMP:Model"] = device.model
        if _field_exists(report, "XMP:LensModel") or _field_exists(report, "XMP-exifEX:LensModel"):
            updates["XMP:LensModel"] = lens_model
        if _field_exists(report, "XMP:CreatorTool") or _field_exists(report, "XMP-xmp:CreatorTool"):
            updates["XMP:CreatorTool"] = software_value
        if _field_exists(report, "SerialNumber"):
            updates["SerialNumber"] = "".join(random.choices("0123456789ABCDEF", k=12))
        if _field_exists(report, "LensSerialNumber"):
            updates["LensSerialNumber"] = "".join(random.choices("0123456789ABCDEF", k=10))
        if _field_exists(report, "CameraSerialNumber"):
            updates["CameraSerialNumber"] = "".join(random.choices("0123456789ABCDEF", k=12))

    updates.update(_filter_device_overrides(device.exif_overrides, report))
    return updates


def _device_updates(profile: SpoofProfile, report: FileReport | None = None) -> dict[str, object]:
    if not (profile.device_make and profile.device_model):
        return {}
    device = next((item for item in get_models_by_make(profile.device_make) if item.model == profile.device_model), None)
    if not device:
        return {}
    return _build_full_device_tags(device, report)


def _device_updates_for_make(make: str | None, current_model: str | None = None, report: FileReport | None = None) -> dict[str, object]:
    device = None
    if make:
        models = get_models_by_make(make)
        if current_model:
            models = [item for item in models if item.model.lower() != current_model.lower()]
        if models:
            device = random.choice(models)
    if device is None:
        all_devices = get_all_devices()
        if make:
            all_devices = [item for item in all_devices if item.make.lower() != make.lower()]
        if all_devices:
            device = random.choice(all_devices)
        else:
            try:
                device = get_random_device(exclude_make=make)
            except RuntimeError:
                return {}
    return _build_full_device_tags(device, report)


def _set_filesystem_dates(destination: Path, fake_date: datetime, exiftool_path: str) -> None:
    # Last exiftool step: earlier writes reset FileModifyDate to "now". FileCreateDate ignored on non-Windows.
    fmt = fake_date.strftime("%Y:%m:%d %H:%M:%S")
    try:
        subprocess.run(
            [
                exiftool_path,
                f"-FileModifyDate={fmt}",
                f"-FileAccessDate={fmt}",
                f"-FileCreateDate={fmt}",
                str(destination),
            ],
            capture_output=True,
            check=False,
            creationflags=get_subprocess_flags(),
        )
    except Exception as exc:  # pragma: no cover - filesystem edge cases
        logging.debug("_set_filesystem_dates failed for %s: %s", destination, exc)


def spoof_filesystem_dates(file_path: Path) -> Path:
    """Overwrite OS file timestamps with a random past date; returns *file_path* for WorkerThread."""

    exiftool_path = get_exiftool_path()
    if not exiftool_path:
        raise RuntimeError("exiftool is required for spoofing.")
    fake_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=random.randint(180, 2000))
    _set_filesystem_dates(file_path, fake_date, exiftool_path)
    return file_path


def set_filesystem_dates(file_path: Path, target_date: datetime) -> Path:
    """Set OS file timestamps to *target_date*; returns *file_path* for WorkerThread."""

    exiftool_path = get_exiftool_path()
    if not exiftool_path:
        raise RuntimeError("exiftool is required for spoofing.")
    _set_filesystem_dates(file_path, target_date, exiftool_path)
    return file_path


def _existing_author_fields(report: FileReport) -> list[MetaField]:
    result: list[MetaField] = []
    for field in report.fields:
        if field.value is None or str(field.value).strip() == "":
            continue
        lowered = field.key.lower()
        normalized = lowered.split(":")[-1].split(".")[-1]
        if normalized in _AUTHOR_EXCLUSIONS:
            continue
        if any(tag in lowered for tag in AUTHOR_TAGS) or normalized == "creator":
            result.append(field)
    return result


def _author_updates(profile: SpoofProfile, report: FileReport | None = None) -> dict[str, str]:
    if not profile.author:
        return {}
    if report is None:
        return {}

    existing = _existing_author_fields(report)
    if not existing:
        return {}

    updates: dict[str, str] = {}
    for field in existing:
        tag = field.exiftool_tag or field.key
        updates[tag] = profile.author
    return updates


def _text_updates(updates: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in updates.items() if value is not None}


def _apply_docx_author(
    destination: Path,
    fake_name: str,
    fields: list[MetaField],
    zip_date: tuple[int, int, int, int, int, int] | None = None,
) -> bool:
    """Write author fields into DOCX core.xml via python-docx."""

    document = Document(str(destination))
    props = document.core_properties
    for field in fields:
        normalized = field.key.lower().split(":")[-1].split(".")[-1]
        if normalized in ("author", "creator", "artist"):
            props.author = fake_name
        elif normalized == "lastmodifiedby":
            props.last_modified_by = fake_name
    document.save(str(destination))
    repack_docx_zip_dates(destination, zip_date or (1980, 1, 1, 0, 0, 0))
    return True


def _author_exists(report: FileReport) -> bool:
    return bool(_existing_author_fields(report))


def apply_field_spoof(
    file_report: FileReport,
    field: MetaField,
    new_value: object,
    *,
    interrupt_check: Callable[[], bool] | None = None,
) -> Path:
    """Run exiftool for one field edit; return path to the working copy."""

    exiftool_path = get_exiftool_path()
    if not exiftool_path:
        raise RuntimeError("exiftool is required for spoofing.")

    final = resolve_spoof_destination(file_report.path)

    def work(destination: Path) -> None:
        clears: list[str] = []
        writes: dict[str, object] = {}

        if field.category == "gps":
            lat = float(new_value["GPSLatitude"]) if isinstance(new_value, dict) else float(new_value[0])
            lon = float(new_value["GPSLongitude"]) if isinstance(new_value, dict) else float(new_value[1])
            clears = list(GPS_TAGS_TO_SPOOF)
            writes = {
                "GPSLatitude": round(lat, 6),
                "GPSLongitude": round(lon, 6),
                "GPSLatitudeRef": "N" if lat >= 0 else "S",
                "GPSLongitudeRef": "E" if lon >= 0 else "W",
                "GPSAltitude": 0,
                "GPSAltitudeRef": 0,
            }
        elif field.category == "device":
            clears = list(DEVICE_TAGS_TO_CLEAR)
            raw_writes = dict(new_value) if isinstance(new_value, dict) else {field.exiftool_tag: new_value}
            writes = {
                tag: value for tag, value in raw_writes.items()
                if tag.split(":")[-1].split(".")[-1] in _CORE_DEVICE_TAGS
                or _field_exists(file_report, tag.split(":")[-1].split(".")[-1])
            }
            existing_profile_creator = _get_field_value(file_report, "ProfileCreator")
            if str(existing_profile_creator).lower() == "appl" and "ProfileCreator" not in writes:
                writes["ProfileCreator"] = "MSFT"
        elif field.category == "dates":
            payload = dict(new_value) if isinstance(new_value, dict) else None
            resolved_date, remove = _resolve_date_value(file_report, payload)
            if not _apply_dates_to_destination(destination, file_report, resolved_date, remove=remove):
                raise RuntimeError("Failed to update date metadata.")
            remove_exiftool_signature(destination, exiftool_path)
            fs_date = resolved_date if resolved_date is not None else (
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=random.randint(180, 2000))
            )
            _set_filesystem_dates(destination, fs_date, exiftool_path)
            return
        else:
            writes = dict(new_value) if isinstance(new_value, dict) else {field.exiftool_tag: new_value}

        _run_exiftool_edits(destination, clears, writes)
        remove_exiftool_signature(destination, exiftool_path)

    run_atomic_file_update(
        file_report.path,
        final,
        work,
        interrupt_check=interrupt_check,
        protected_path_for_log=file_report.path,
    )
    return final


def apply_spoof(
    file_report: FileReport,
    profile: SpoofProfile,
    *,
    interrupt_check: Callable[[], bool] | None = None,
) -> Path:
    """Apply *profile* to the working copy and return its path."""

    exiftool_path = get_exiftool_path()
    if not exiftool_path:
        raise RuntimeError("exiftool is required for spoofing.")

    final = resolve_spoof_destination(file_report.path)

    def work(destination: Path) -> None:
        clears: list[str] = []
        writes: dict[str, object] = {}

        has_gps_metadata = _find_gps_field(file_report) is not None
        gps_target = _resolve_gps_target(file_report, profile)
        if has_gps_metadata and profile.gps_mode == "remove":
            clears.extend(GPS_TAGS_TO_SPOOF)
        elif has_gps_metadata and gps_target:
            lat, lon = gps_target
            clears.extend(GPS_TAGS_TO_SPOOF)
            writes.update(
                {
                    "GPSLatitude": round(lat, 6),
                    "GPSLongitude": round(lon, 6),
                    "GPSLatitudeRef": "N" if lat >= 0 else "S",
                    "GPSLongitudeRef": "E" if lon >= 0 else "W",
                    "GPSAltitude": 0,
                    "GPSAltitudeRef": 0,
                }
            )

        device_updates = _device_updates(profile, report=file_report)
        if device_updates:
            clears.extend(DEVICE_TAGS_TO_CLEAR)
            writes.update(device_updates)
            existing_profile_creator = _get_field_value(file_report, "ProfileCreator")
            if str(existing_profile_creator).lower() == "appl" and "ProfileCreator" not in writes:
                writes["ProfileCreator"] = "MSFT"

        if file_report.file_type.lower() != "docx":
            writes.update(_author_updates(profile, file_report))

        _run_exiftool_edits(destination, list(dict.fromkeys(clears)), writes)

        if file_report.file_type.lower() == "docx" and profile.author:
            docx_author_fields = _existing_author_fields(file_report)
            if docx_author_fields:
                _apply_docx_author(destination, profile.author, docx_author_fields)

        fs_date: datetime | None = None
        if profile.dates_mode != "keep":
            if profile.dates_mode == "remove":
                _apply_dates_to_destination(destination, file_report, None, remove=True)
                fs_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=random.randint(180, 2000))
            else:
                date_updates = _build_date_updates(file_report, profile)
                anchor = parse_metadata_datetime(next(iter(date_updates.values()), None)) if date_updates else None
                resolved = anchor or _resolve_date_value(file_report)[0]
                if resolved is not None and not _apply_dates_to_destination(destination, file_report, resolved, remove=False):
                    raise RuntimeError("Failed to update date metadata.")
                fs_date = resolved

        remove_exiftool_signature(destination, exiftool_path)
        if fs_date is not None:
            _set_filesystem_dates(destination, fs_date, exiftool_path)

    run_atomic_file_update(
        file_report.path,
        final,
        work,
        interrupt_check=interrupt_check,
        protected_path_for_log=file_report.path,
    )
    return final


def apply_smart_spoof(
    file_report: FileReport,
    progress_callback=None,
    output_path: Path | None = None,
    *,
    interrupt_check: Callable[[], bool] | None = None,
) -> tuple[Path, list[str], list[str]]:
    """Spoof GPS, device, dates, author, etc.

    Returns ``(destination, changes, info_codes)``. ``info_codes`` are theme keys for UX (e.g. GPS skipped).
    """

    exiftool_path = get_exiftool_path()
    if not exiftool_path:
        raise RuntimeError("exiftool is required for spoofing.")

    if output_path is not None:
        final = Path(output_path)
        final.parent.mkdir(parents=True, exist_ok=True)
    else:
        final = resolve_spoof_destination(file_report.path)

    changes: list[str] = []
    info_codes: list[str] = []

    def add_info(code: str) -> None:
        if code not in info_codes:
            info_codes.append(code)

    def progress(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    def work(destination: Path) -> None:
        gps_lat = _find_field(file_report, "gpslatitude")
        gps_lon = _find_field(file_report, "gpslongitude")
        if gps_lat and gps_lon and gps_lat.value not in (None, "") and gps_lon.value not in (None, ""):
            progress("Spoofing GPS...")
            if not geo_validator.has_country_data():
                logging.error("Smart spoof GPS skipped: countries.geojson not found")
                progress("Skipping GPS spoof - countries.geojson not found")
                add_info("smart_spoof_skip_gps_no_country_data")
            else:
                try:
                    lat, lon = geo_validator.smart_spoof(float(gps_lat.value), float(gps_lon.value))
                    if _run_exiftool_edits(
                        destination,
                        list(GPS_TAGS_TO_SPOOF),
                        {
                            "GPSLatitude": round(lat, 6),
                            "GPSLongitude": round(lon, 6),
                            "GPSLatitudeRef": "N" if lat >= 0 else "S",
                            "GPSLongitudeRef": "E" if lon >= 0 else "W",
                            "GPSAltitude": 0,
                            "GPSAltitudeRef": 0,
                        },
                        soft_fail=True,
                    ):
                        changes.append("gps")
                    else:
                        add_info("smart_spoof_partial_gps_failed")
                except Exception as exc:
                    logging.error("Smart spoof GPS failed: %s", exc, exc_info=True)
                    add_info("smart_spoof_partial_gps_failed")

        has_valid_gps_pair = (
            gps_lat is not None
            and gps_lon is not None
            and gps_lat.value not in (None, "")
            and gps_lon.value not in (None, "")
        )
        has_sensitive_gps = any(f.category == "gps" and f.is_sensitive for f in file_report.fields)
        if has_sensitive_gps and not has_valid_gps_pair:
            add_info("smart_spoof_skip_gps_no_source")

        current_make = _get_field_value(file_report, "Make")
        current_model = _get_field_value(file_report, "Model")
        if current_make:
            progress("Spoofing device...")
            try:
                device_updates = _device_updates_for_make(
                    str(current_make),
                    str(current_model) if current_model else None,
                    report=file_report,
                )
                if device_updates:
                    existing_profile_creator = _get_field_value(file_report, "ProfileCreator")
                    if str(existing_profile_creator).lower() == "appl" and "ProfileCreator" not in device_updates:
                        device_updates["ProfileCreator"] = "MSFT"
                    if _run_exiftool_edits(destination, list(DEVICE_TAGS_TO_CLEAR), device_updates, soft_fail=True):
                        changes.append("device")
                    else:
                        add_info("smart_spoof_partial_device_failed")
                else:
                    logging.error("Smart spoof device skipped: no devices available in DB")
                    progress("Skipping device spoof - no devices in DB")
                    add_info("smart_spoof_skip_device_no_candidates")
            except Exception as exc:
                logging.error("Smart spoof device failed: %s", exc, exc_info=True)
                add_info("smart_spoof_partial_device_failed")

        has_dates = any(
            ("date" in field.key.lower() or "time" in field.key.lower()) and field.is_sensitive
            for field in file_report.fields
        )
        dates_anchor: datetime | None = None
        if has_dates:
            progress("Spoofing dates...")
            try:
                shift_days = -random.randint(180, 1000)
                base_date = _resolve_date_value(file_report)[0] or datetime.now(timezone.utc).replace(tzinfo=None)
                anchor = base_date + timedelta(days=shift_days)
                if _apply_dates_to_destination(destination, file_report, anchor, remove=False):
                    changes.append("dates")
                    dates_anchor = anchor
                else:
                    add_info("smart_spoof_partial_dates_failed")
            except Exception as exc:
                logging.error("Smart spoof dates failed: %s", exc, exc_info=True)
                add_info("smart_spoof_partial_dates_failed")

        if _author_exists(file_report):
            progress("Spoofing author...")
            try:
                try:
                    from faker import Faker

                    fake_name = Faker().name()
                except Exception:
                    fake_name = "John Smith"
                existing_author_fields = _existing_author_fields(file_report)
                if file_report.file_type.lower() == "docx":
                    zip_dt = _datetime_to_zip_time(dates_anchor) if dates_anchor else None
                    _apply_docx_author(destination, fake_name, existing_author_fields, zip_date=zip_dt)
                    changes.append("author")
                elif _run_exiftool_edits(
                    destination,
                    [],
                    _text_updates({(field.exiftool_tag or field.key): fake_name for field in existing_author_fields}),
                    soft_fail=True,
                ):
                    changes.append("author")
                else:
                    add_info("smart_spoof_partial_author_failed")
            except Exception as exc:
                logging.error("Smart spoof author failed: %s", exc, exc_info=True)
                add_info("smart_spoof_partial_author_failed")

        if _find_field(file_report, "software") and "device" not in changes:
            progress("Spoofing software...")
            try:
                software_value = random.choice(
                    [
                        "Adobe Photoshop 24.0",
                        "GIMP 2.10",
                        "Lightroom 12.0",
                        "Capture One 23",
                    ]
                )
                sw_writes: dict[str, object] = {"Software": software_value}
                if _field_exists(file_report, "CreatorTool"):
                    sw_writes["CreatorTool"] = software_value
                if _field_exists(file_report, "XMP:CreatorTool") or _field_exists(file_report, "creatortool"):
                    sw_writes["XMP:CreatorTool"] = software_value
                if _run_exiftool_edits(destination, [], sw_writes, soft_fail=True):
                    changes.append("software")
                else:
                    add_info("smart_spoof_partial_software_failed")
            except Exception as exc:
                logging.error("Smart spoof software failed: %s", exc, exc_info=True)
                add_info("smart_spoof_partial_software_failed")

        serial_field = _find_field(file_report, "SerialNumber")
        if serial_field and serial_field.key == "SerialNumber":
            progress("Spoofing serial...")
            try:
                fake_serial = "".join(random.choices("0123456789ABCDEF", k=12))
                if not _run_exiftool_edits(destination, [], {"SerialNumber": fake_serial}, soft_fail=True):
                    add_info("smart_spoof_partial_raw_failed")
            except Exception as exc:
                logging.error("Smart spoof serial failed: %s", exc, exc_info=True)
                add_info("smart_spoof_partial_raw_failed")

        if file_report.file_type == "raw":
            progress("Spoofing RAW identifiers...")
            try:
                raw_updates = _raw_sensitive_updates(file_report)
                if raw_updates:
                    if not _run_exiftool_edits(destination, [], raw_updates, soft_fail=True):
                        add_info("smart_spoof_partial_raw_failed")
            except Exception as exc:
                logging.error("Smart spoof RAW identifiers failed: %s", exc, exc_info=True)
                add_info("smart_spoof_partial_raw_failed")

        region_cleanup_ok, non_region_cleanup_ok = _nuke_always_delete_tags(destination, file_report)
        if not region_cleanup_ok:
            add_info("smart_spoof_partial_region_cleanup_failed")
        if not non_region_cleanup_ok:
            add_info("smart_spoof_partial_non_region_cleanup_failed")

        remove_exiftool_signature(destination, exiftool_path)
        if dates_anchor is not None:
            _set_filesystem_dates(destination, dates_anchor, exiftool_path)

    run_atomic_file_update(
        file_report.path,
        final,
        work,
        interrupt_check=interrupt_check,
        protected_path_for_log=file_report.path,
    )
    logging.debug("spoofed changes: %s", changes)
    progress("Done")
    return final, changes, info_codes
