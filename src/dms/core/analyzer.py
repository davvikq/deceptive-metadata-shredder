"""Metadata analysis across supported file types."""

from __future__ import annotations

import io
import json
import logging
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import piexif
from docx import Document
from PIL import Image
from pypdf import PdfReader

from dms.config import get_exiftool_path, get_exiftool_version, require_exiftool
from dms.core.constants import ALWAYS_DELETE_PREFIXES, ALWAYS_DELETE_TAGS, SENSITIVE_EXACT_TAGS, SENSITIVE_KEYWORDS, SENSITIVE_PARTIAL_TAGS, TECHNICAL_TAGS
from dms.core.models import FileReport, MetaField
from dms.core.utils import get_subprocess_flags

SUPPORTED_FORMATS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".heic": "heic",
    ".heif": "heif",
    ".png": "png",
    ".pdf": "pdf",
    ".docx": "docx",
    ".mp4": "mp4",
    ".mov": "mov",
    ".tiff": "tiff",
    ".tif": "tiff",
    ".webp": "webp",
    ".cr2": "raw",
    ".cr3": "raw",
    ".nef": "raw",
    ".nrw": "raw",
    ".arw": "raw",
    ".srf": "raw",
    ".sr2": "raw",
    ".dng": "raw",
    ".raf": "raw",
    ".orf": "raw",
    ".rw2": "raw",
    ".pef": "raw",
    ".x3f": "raw",
}

IMAGE_SUFFIXES = {suffix for suffix, kind in SUPPORTED_FORMATS.items() if kind in {"jpeg", "png", "heic", "heif", "tiff", "webp"}}
VIDEO_SUFFIXES = {".mp4", ".mov"}
DOC_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}
HEIC_SUFFIXES = {".heic", ".heif"}
RAW_SUFFIXES = {suffix for suffix, kind in SUPPORTED_FORMATS.items() if kind == "raw"}
RAW_READONLY_TAGS = {"InternalSerialNumber"}

FIELD_DEFINITIONS: dict[str, tuple[str, str, bool]] = {
    "GPSLatitude": ("GPS Latitude", "gps", True),
    "GPSLongitude": ("GPS Longitude", "gps", True),
    "GPSAltitude": ("GPS Altitude", "gps", True),
    "GPSPosition": ("GPS Position", "gps", False),
    "GPSSpeed": ("GPS Speed", "gps", True),
    "GPSImgDirection": ("GPS Image Direction", "gps", True),
    "GPSDestBearing": ("GPS Destination Bearing", "gps", True),
    "GPSHPositioningError": ("GPS Horizontal Error", "gps", True),
    "GPSTimeStamp": ("GPS Time Stamp", "dates", True),
    "GPSDateStamp": ("GPS Date Stamp", "dates", True),
    "GPSDateTime": ("GPS DateTime", "dates", True),
    "Make": ("Device Make", "device", True),
    "Model": ("Device Model", "device", True),
    "Software": ("Software", "device", True),
    "LensModel": ("Lens Model", "device", True),
    "LensID": ("Lens ID", "device", True),
    "LensSerialNumber": ("Lens Serial Number", "device", True),
    "CameraSerialNumber": ("Camera Serial Number", "device", True),
    "CreatorTool": ("Creator Tool", "device", True),
    "HostComputer": ("Host Computer", "device", True),
    "UniqueCameraModel": ("Unique Camera Model", "device", True),
    "SerialNumber": ("Serial Number", "device", True),
    "InternalSerialNumber": ("Internal Serial Number", "device", True),
    "OwnerName": ("Owner Name", "author", True),
    "ImageUniqueID": ("Image Unique ID", "other", True),
    "Author": ("Author", "author", True),
    "Creator": ("Creator", "author", True),
    "Artist": ("Artist", "author", True),
    "Owner": ("Owner", "author", True),
    "Producer": ("Producer", "author", True),
    "Title": ("Title", "other", False),
    "Subject": ("Subject", "other", False),
    "Description": ("Description", "other", True),
    "Comment": ("Comment", "other", True),
    "UserComment": ("User Comment", "other", True),
    "Copyright": ("Copyright", "other", True),
    "Company": ("Company", "author", True),
    "LastModifiedBy": ("Last Modified By", "author", True),
    "CreateDate": ("Create Date", "dates", True),
    "CreationDate": ("Creation Date", "dates", True),
    "DateTimeOriginal": ("Captured At", "dates", True),
    "ModifyDate": ("Modified At", "dates", True),
    "ModDate": ("PDF Modified", "dates", True),
    "Created": ("Created", "dates", True),
    "Modified": ("Modified", "dates", True),
    "Revision": ("Revision", "other", False),
    "PDFVersion": ("PDF Version", "other", False),
    "HasTrackedChanges": ("Tracked Changes", "other", False),
}

def _normalized_tag_name(tag: str) -> str:
    return tag.split(".")[-1].split(":")[-1]


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_tag_name(key)
    if normalized in TECHNICAL_TAGS:
        return False
    if any(keyword in normalized for keyword in SENSITIVE_KEYWORDS):
        return True
    if normalized in SENSITIVE_EXACT_TAGS:
        return True
    for fragment in SENSITIVE_PARTIAL_TAGS:
        if fragment in normalized:
            return True
    if normalized.startswith("Region"):
        return True
    return False


def find_exiftool() -> str:
    """Resolve exiftool path from config (bundled bin/) or PATH."""

    path = get_exiftool_path()
    if path is not None:
        return path
    raise FileNotFoundError("exiftool not found in bin/ folder or system PATH")


def detect_file_type(path: Path) -> str:
    """Map file extension to internal type label (jpeg, heic, raw, …)."""

    suffix = path.suffix.lower()
    return SUPPORTED_FORMATS.get(suffix, suffix.removeprefix(".") or "unknown")


def _run_exiftool_json(path: Path) -> dict[str, Any]:
    exiftool = find_exiftool()
    result = subprocess.run(
        [exiftool, "-json", "-n", "-a", "-u", "-G1", "-l", str(path)],
        check=True,
        capture_output=True,
        text=True,
        creationflags=get_subprocess_flags(),
    )
    payload = json.loads(result.stdout)
    return payload[0] if payload else {}


def _run_exiftool_pdf_json(path: Path) -> dict[str, Any]:
    exiftool = find_exiftool()
    result = subprocess.run(
        [exiftool, "-json", "-pdf:all", "-xmp:all", str(path)],
        check=True,
        capture_output=True,
        text=True,
        creationflags=get_subprocess_flags(),
    )
    payload = json.loads(result.stdout)
    return payload[0] if payload else {}


def _extract_thumbnail(path: Path) -> bytes | None:
    try:
        exiftool = find_exiftool()
    except FileNotFoundError:
        return None
    result = subprocess.run(
        [exiftool, "-b", "-ThumbnailImage", str(path)],
        check=False,
        capture_output=True,
        creationflags=get_subprocess_flags(),
    )
    return result.stdout or None


def _safe_append(
    fields: list[MetaField],
    exiftool_tag: str,
    value: Any,
    *,
    label_override: str | None = None,
    file_type: str | None = None,
) -> None:
    if value in (None, "", []):
        return
    normalized_key = _normalized_tag_name(exiftool_tag)
    label, category, spoofable = FIELD_DEFINITIONS.get(
        normalized_key,
        (label_override or normalized_key.replace("_", " "), "other", False),
    )
    is_sensitive = _is_sensitive_key(normalized_key)
    fields.append(
        MetaField(
            exiftool_tag=exiftool_tag,
            key=normalized_key,
            label=label,
            value=value,
            category=category,
            spoofable=spoofable,
            is_sensitive=is_sensitive,
            is_computed=(
                exiftool_tag.startswith("Composite:")
                or (file_type == "raw" and normalized_key in RAW_READONLY_TAGS)
                or normalized_key in ALWAYS_DELETE_TAGS
                or any(normalized_key.startswith(p) for p in ALWAYS_DELETE_PREFIXES)
            ),
            status="risk" if is_sensitive else "clean",
        )
    )


def _analyze_with_exiftool(path: Path) -> list[MetaField]:
    raw = _run_exiftool_json(path)
    fields: list[MetaField] = []
    seen_keys: set[str] = set()
    _append_grouped_fields(fields, raw, seen_keys, file_type=detect_file_type(path))
    return fields


def _append_grouped_fields(
    fields: list[MetaField],
    payload: dict[str, Any],
    seen_tags: set[str],
    parents: tuple[str, ...] = (),
    file_type: str | None = None,
) -> None:
    for key, value in payload.items():
        if isinstance(value, dict) and "val" in value:
            field_tag = ".".join((*parents, key)) if parents else key
            normalized_key = _normalized_tag_name(field_tag)
            if normalized_key in seen_tags:
                continue
            seen_tags.add(normalized_key)
            _safe_append(fields, field_tag, value.get("val"), label_override=value.get("desc"), file_type=file_type)
            continue

        if isinstance(value, dict):
            _append_grouped_fields(fields, value, seen_tags, parents + (key,), file_type=file_type)
            continue

        field_tag = ".".join((*parents, key)) if parents else key
        normalized_key = _normalized_tag_name(field_tag)
        if normalized_key in seen_tags:
            continue
        seen_tags.add(normalized_key)
        _safe_append(fields, field_tag, value, file_type=file_type)


def _analyze_image_fallback(path: Path) -> list[MetaField]:
    fields: list[MetaField] = []
    with Image.open(path) as image:
        exif = image.getexif()
        tag_map = {
            271: "Make",
            272: "Model",
            305: "Software",
            306: "ModifyDate",
            36867: "DateTimeOriginal",
            36868: "CreateDate",
        }
        for tag, name in tag_map.items():
            _safe_append(fields, name, exif.get(tag))
        exif_ifd = exif.get_ifd(34665) if hasattr(exif, "get_ifd") else {}
        for tag, name in {
            36867: "DateTimeOriginal",
            36868: "CreateDate",
            42036: "LensModel",
        }.items():
            _safe_append(fields, name, exif_ifd.get(tag))
        gps = exif.get_ifd(34853) if hasattr(exif, "get_ifd") else {}
        if gps:
            lat = gps.get(2)
            lon = gps.get(4)
            lat_ref = gps.get(1, "N")
            lon_ref = gps.get(3, "E")
            alt = gps.get(6)
            if lat:
                value = _rational_to_degrees(lat)
                if value is not None:
                    if str(lat_ref).upper().startswith("S"):
                        value *= -1
                    _safe_append(fields, "GPSLatitude", value)
            if lon:
                value = _rational_to_degrees(lon)
                if value is not None:
                    if str(lon_ref).upper().startswith("W"):
                        value *= -1
                    _safe_append(fields, "GPSLongitude", value)
            if alt is not None:
                _safe_append(fields, "GPSAltitude", alt)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        _merge_piexif_fields(path, fields)
    return fields


def _merge_piexif_fields(path: Path, fields: list[MetaField]) -> None:
    existing = {field.key for field in fields}
    payload = piexif.load(str(path))
    zeroth = payload.get("0th", {})
    exif_ifd = payload.get("Exif", {})
    gps_ifd = payload.get("GPS", {})

    tag_maps = [
        (zeroth, {piexif.ImageIFD.Make: "Make", piexif.ImageIFD.Model: "Model", piexif.ImageIFD.Software: "Software"}),
        (
            exif_ifd,
            {
                piexif.ExifIFD.DateTimeOriginal: "DateTimeOriginal",
                piexif.ExifIFD.DateTimeDigitized: "CreateDate",
                piexif.ExifIFD.LensModel: "LensModel",
            },
        ),
    ]
    for payload_block, tag_map in tag_maps:
        for tag, name in tag_map.items():
            if name in existing:
                continue
            value = payload_block.get(tag)
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore").strip("\x00")
            _safe_append(fields, name, value)

    if "GPSLatitude" not in existing and gps_ifd.get(piexif.GPSIFD.GPSLatitude):
        lat = _rational_to_degrees(gps_ifd[piexif.GPSIFD.GPSLatitude])
        if lat is not None:
            lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
            if isinstance(lat_ref, bytes):
                lat_ref = lat_ref.decode("utf-8", errors="ignore")
            if str(lat_ref).upper().startswith("S"):
                lat *= -1
            _safe_append(fields, "GPSLatitude", lat)
    if "GPSLongitude" not in existing and gps_ifd.get(piexif.GPSIFD.GPSLongitude):
        lon = _rational_to_degrees(gps_ifd[piexif.GPSIFD.GPSLongitude])
        if lon is not None:
            lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef, b"E")
            if isinstance(lon_ref, bytes):
                lon_ref = lon_ref.decode("utf-8", errors="ignore")
            if str(lon_ref).upper().startswith("W"):
                lon *= -1
            _safe_append(fields, "GPSLongitude", lon)
    if "GPSAltitude" not in existing and gps_ifd.get(piexif.GPSIFD.GPSAltitude):
        altitude = gps_ifd[piexif.GPSIFD.GPSAltitude]
        if isinstance(altitude, tuple):
            altitude = altitude[0] / altitude[1]
        _safe_append(fields, "GPSAltitude", altitude)


def _rational_to_degrees(rational: Any) -> float | None:
    """Convert EXIF DMS rationals to decimal degrees, or None if data is invalid."""

    if rational is None:
        return None
    try:
        items = list(rational)
    except (TypeError, AttributeError):
        return None
    if len(items) != 3:
        return None
    values: list[float] = []
    for item in items:
        if isinstance(item, tuple):
            if len(item) != 2:
                return None
            try:
                num, den = item[0], item[1]
                denom = float(den)
                if denom == 0:
                    return None
                values.append(float(num) / denom)
            except (TypeError, ValueError, ZeroDivisionError):
                return None
        else:
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                return None
    degrees, minutes, seconds = values
    return round(degrees + minutes / 60 + seconds / 3600, 6)


def _analyze_pdf(path: Path) -> list[MetaField]:
    fields: list[MetaField] = []
    if get_exiftool_path():
        seen_keys: set[str] = set()
        _append_grouped_fields(fields, _run_exiftool_json(path), seen_keys)
        _append_grouped_fields(fields, _run_exiftool_pdf_json(path), seen_keys)
    # Keep binary stream open while PdfReader reads metadata (avoids lingering FDs on some backends).
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        metadata = reader.metadata or {}
        header = getattr(reader, "pdf_header", b"%PDF-1.0")
        if isinstance(header, bytes):
            version = header.decode("latin-1", errors="ignore").replace("%PDF-", "")
        else:
            version = str(header).replace("%PDF-", "")
        pdf_extras = {
            "Author": metadata.get("/Author"),
            "Creator": metadata.get("/Creator"),
            "Producer": metadata.get("/Producer"),
            "Title": metadata.get("/Title"),
            "Subject": metadata.get("/Subject"),
            "CreationDate": metadata.get("/CreationDate"),
            "ModDate": metadata.get("/ModDate"),
            "PDFVersion": version,
        }
    for key, value in pdf_extras.items():
        if not any(field.key == key for field in fields):
            _safe_append(fields, key, value)
    return fields


def _analyze_docx(path: Path) -> list[MetaField]:
    fields = _analyze_with_exiftool(path) if get_exiftool_path() else []
    # Load from memory so python-docx does not hold an open file handle to path.
    document = Document(io.BytesIO(path.read_bytes()))
    props = document.core_properties
    for key, value in {
        "Author": props.author,
        "LastModifiedBy": props.last_modified_by,
        "Company": getattr(props, "company", None),
        "Created": props.created,
        "Modified": props.modified,
        "Revision": props.revision,
    }.items():
        if not any(field.key == key for field in fields):
            _safe_append(fields, key, value)
    has_tracked_changes = False
    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" in archive.namelist():
            content = archive.read("word/document.xml").decode("utf-8", errors="ignore")
            has_tracked_changes = "<w:ins" in content or "<w:del" in content
    if not any(field.key == "HasTrackedChanges" for field in fields):
        _safe_append(fields, "HasTrackedChanges", has_tracked_changes)
    return fields


def _version_number(version: str | None) -> float | None:
    if not version:
        return None
    try:
        return float(version.strip())
    except ValueError:
        return None


def _read_exiftool_version(exiftool_path: str) -> float | None:
    try:
        result = subprocess.run(
            [exiftool_path, "-ver"],
            capture_output=True,
            text=True,
            check=True,
            creationflags=get_subprocess_flags(),
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def _report_warnings(path: Path) -> list[str]:
    warnings: list[str] = []
    try:
        exiftool_path = find_exiftool()
    except FileNotFoundError:
        exiftool_path = None
    if not exiftool_path:
        warnings.append("exiftool not found. Install it for full metadata support.")
    if path.suffix.lower() in HEIC_SUFFIXES:
        version_number = _read_exiftool_version(exiftool_path) if exiftool_path else None
        if version_number is not None and version_number < 12.0:
            warnings.append("HEIC metadata support requires exiftool 12 or newer.")
    if detect_file_type(path) == "raw":
        warnings.append("RAW file - some embedded tags cannot be modified. Consider working with a DNG copy for full metadata control.")
    return warnings


def _build_report(
    path: Path,
    file_type: str,
    fields: list[MetaField],
    thumbnail: bytes | None,
    warnings: list[str],
) -> FileReport:
    empty_reason = None
    if not fields:
        empty_reason = (
            "No metadata found - the file may already be clean,\n"
            "or exiftool couldn't read this format."
        )
    return FileReport(
        path=path,
        file_type=file_type,
        fields=fields,
        thumbnail=thumbnail,
        warnings=warnings,
        empty_reason=empty_reason,
        exiftool_version=get_exiftool_version(),
    )


def analyze(path: Path) -> FileReport:
    """Read metadata from *path* and return a structured report."""

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    file_type = detect_file_type(file_path)
    suffix = file_path.suffix.lower()
    warnings = _report_warnings(file_path)

    if suffix in IMAGE_SUFFIXES:
        if suffix in HEIC_SUFFIXES:
            try:
                fields = _analyze_with_exiftool(file_path)
            except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError):
                fields = []
        else:
            try:
                fields = _analyze_with_exiftool(file_path)
            except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError):
                fields = _analyze_image_fallback(file_path)
        thumbnail = _extract_thumbnail(file_path)
        if thumbnail is None and suffix in {".jpg", ".jpeg", ".tiff", ".tif", ".webp"}:
            with Image.open(file_path) as image:
                preview = image.copy()
                preview.thumbnail((256, 256))
                buffer = io.BytesIO()
                preview.save(buffer, format="JPEG")
                thumbnail = buffer.getvalue()
        return _build_report(file_path, file_type, fields, thumbnail, warnings)

    if suffix in PDF_SUFFIXES:
        try:
            fields = _analyze_pdf(file_path)
        except Exception:
            logging.exception("Failed to analyze PDF: %s", file_path)
            fields = []
        return _build_report(file_path, file_type, fields, None, warnings)

    if suffix in DOC_SUFFIXES:
        try:
            fields = _analyze_docx(file_path)
        except Exception:
            logging.exception("Failed to analyze DOCX: %s", file_path)
            fields = []
        return _build_report(file_path, file_type, fields, None, warnings)

    if suffix in VIDEO_SUFFIXES:
        try:
            fields = _analyze_with_exiftool(file_path)
        except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError):
            fields = []
        return _build_report(file_path, file_type, fields, None, warnings)

    try:
        fields = _analyze_with_exiftool(file_path)
    except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError):
        fields = []
    return _build_report(file_path, file_type, fields, None, warnings)
