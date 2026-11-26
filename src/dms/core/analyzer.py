"""Metadata analysis across supported file types."""

from __future__ import annotations

import io
import json
import logging
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import piexif
from docx import Document
from PIL import Image
from pypdf import PdfReader

from dms.config import get_exiftool_path, get_exiftool_version, require_exiftool
from dms.core.constants import ALWAYS_DELETE_PREFIXES, ALWAYS_DELETE_TAGS, SENSITIVE_EXACT_TAGS, SENSITIVE_KEYWORDS, SENSITIVE_PARTIAL_TAGS, TECHNICAL_TAGS
from dms.core.models import FileReport, MetaField
from dms.core.utils import EXIFTOOL_TEXT_KWARGS, EXIFTOOL_TIMEOUT, get_subprocess_flags

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
IMAGE_PARSE_WARNING = "Image metadata could not be fully parsed. Showing limited report."
IMAGE_THUMBNAIL_WARNING = "Could not render image preview thumbnail."
ANALYSIS_LIMITED_WARNING = "Metadata analysis is limited; verification cannot guarantee this file is clean."
PDF_LIMITATION_WARNING = (
    "Standard PDF cleaning strips document info and annotation authors, "
    "but preserves annotation text, form values, attachments, and embedded image metadata."
)
ZERO_DATE_PREFIXES = ("0000:00:00", "0000-00-00")


class MetadataAnalysisError(RuntimeError):
    """Raised when metadata could not be read completely enough to verify a file."""

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
    "FileModifyDate": ("File Modified (filesystem)", "dates", True),
    "FileCreateDate": ("File Created (filesystem)", "dates", True),
    "FileAccessDate": ("File Accessed (filesystem)", "dates", True),
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
        [exiftool, "-json", "-n", "-a", "-u", "-G1", "-l", "-charset", "filename=UTF8", str(path)],
        check=True,
        capture_output=True,
        timeout=EXIFTOOL_TIMEOUT,
        creationflags=get_subprocess_flags(),
        **EXIFTOOL_TEXT_KWARGS,
    )
    if not (result.stdout or "").strip():
        raise MetadataAnalysisError("exiftool returned no metadata output.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MetadataAnalysisError(f"exiftool returned invalid JSON: {exc}") from exc
    if not payload or not payload[0]:
        raise MetadataAnalysisError("exiftool returned an empty metadata report.")
    return payload[0]


def _run_exiftool_pdf_json(path: Path) -> dict[str, Any]:
    exiftool = find_exiftool()
    result = subprocess.run(
        [exiftool, "-json", "-G1", "-pdf:all", "-xmp:all", "-charset", "filename=UTF8", str(path)],
        check=True,
        capture_output=True,
        timeout=EXIFTOOL_TIMEOUT,
        creationflags=get_subprocess_flags(),
        **EXIFTOOL_TEXT_KWARGS,
    )
    if not (result.stdout or "").strip():
        raise MetadataAnalysisError("exiftool returned no PDF metadata output.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MetadataAnalysisError(f"exiftool returned invalid PDF JSON: {exc}") from exc
    if not payload or not payload[0]:
        raise MetadataAnalysisError("exiftool returned an empty PDF metadata report.")
    return payload[0]


def _extract_thumbnail(path: Path) -> bytes | None:
    try:
        exiftool = find_exiftool()
    except FileNotFoundError:
        return None
    try:
        result = subprocess.run(
            [exiftool, "-b", "-ThumbnailImage", str(path)],
            check=False,
            capture_output=True,
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
        )
    except subprocess.SubprocessError:
        return None
    return result.stdout or None


def _is_zero_datetime(value: Any) -> bool:
    text = str(value).strip() if value is not None else ""
    return text.startswith(ZERO_DATE_PREFIXES)


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
    is_sensitive = (
        _is_sensitive_key(normalized_key)
        and not _is_zero_datetime(value)
        and not exiftool_tag.upper().startswith("ZIP:")
        and normalized_key not in {"ZipModifyDate", "ZipCreateDate"}
    )
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
    seen_tags: set[str] = set()
    seen_keys: set[str] = set()
    _append_grouped_fields(fields, raw, seen_tags, seen_keys, file_type=detect_file_type(path))
    return fields


def _is_duplicate_field(
    field_tag: str,
    normalized_key: str,
    seen_tags: set[str],
    seen_keys: set[str],
) -> bool:
    """Keep different group variants (e.g. IFD0:Software and XMP-tiff:Software).

    Only exact tags repeat, plus Composite values that merely derive from a tag
    already present in the report.
    """

    identity = field_tag.lower()
    if identity in seen_tags:
        return True
    seen_tags.add(identity)
    if field_tag.startswith("Composite:") and normalized_key in seen_keys:
        return True
    seen_keys.add(normalized_key)
    return False


def _append_grouped_fields(
    fields: list[MetaField],
    payload: dict[str, Any],
    seen_tags: set[str],
    seen_keys: set[str],
    parents: tuple[str, ...] = (),
    file_type: str | None = None,
) -> None:
    for key, value in payload.items():
        if isinstance(value, dict) and "val" in value:
            field_tag = ".".join((*parents, key)) if parents else key
            normalized_key = _normalized_tag_name(field_tag)
            if _is_duplicate_field(field_tag, normalized_key, seen_tags, seen_keys):
                continue
            _safe_append(fields, field_tag, value.get("val"), label_override=value.get("desc"), file_type=file_type)
            continue

        if isinstance(value, dict):
            _append_grouped_fields(fields, value, seen_tags, seen_keys, parents + (key,), file_type=file_type)
            continue

        field_tag = ".".join((*parents, key)) if parents else key
        normalized_key = _normalized_tag_name(field_tag)
        if _is_duplicate_field(field_tag, normalized_key, seen_tags, seen_keys):
            continue
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


def _analyze_pdf(path: Path) -> tuple[list[MetaField], str, str | None, list[str]]:
    fields: list[MetaField] = []
    status = "ok"
    error: str | None = None
    pdf_warnings: list[str] = [PDF_LIMITATION_WARNING]
    if get_exiftool_path():
        seen_tags: set[str] = set()
        seen_keys: set[str] = set()
        try:
            _append_grouped_fields(fields, _run_exiftool_json(path), seen_tags, seen_keys)
            _append_grouped_fields(fields, _run_exiftool_pdf_json(path), seen_tags, seen_keys)
        except (RuntimeError, subprocess.SubprocessError, OSError, json.JSONDecodeError, MetadataAnalysisError) as exc:
            status = "partial"
            error = f"exiftool PDF read failed: {exc}"
            logging.warning("exiftool PDF read failed for %s: %s", path, exc)
    else:
        status = "partial"
        error = "exiftool not found; PDF analysis is limited."
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
        annot_count = sum(len(page.get("/Annots") or []) for page in reader.pages)
        attach_count = len(reader.attachments)
        root = reader.trailer.get("/Root")
        has_form = bool(root and "/AcroForm" in root.get_object())
        details: list[str] = []
        if annot_count:
            details.append(f"{annot_count} annotation(s)")
        if attach_count:
            details.append(f"{attach_count} attachment(s)")
        if has_form:
            details.append("interactive form fields")
        if details:
            pdf_warnings.append(
                f"PDF contains {', '.join(details)}. "
                "Use --strip-annotations / --strip-attachments to remove annotations or attachments."
            )
    for key, value in pdf_extras.items():
        if not any(field.key == key for field in fields):
            _safe_append(fields, key, value)
    return fields, status, error, pdf_warnings


def _analyze_docx(path: Path) -> tuple[list[MetaField], str, str | None]:
    fields: list[MetaField] = []
    status = "ok"
    error: str | None = None
    if get_exiftool_path():
        try:
            fields = _analyze_with_exiftool(path)
        except (RuntimeError, subprocess.SubprocessError, OSError, json.JSONDecodeError, MetadataAnalysisError) as exc:
            status = "partial"
            error = f"exiftool DOCX read failed: {exc}"
            logging.warning("exiftool DOCX read failed for %s: %s", path, exc)
    else:
        status = "partial"
        error = "exiftool not found; DOCX analysis is limited."
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
    return fields, status, error


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
            check=True,
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
            **EXIFTOOL_TEXT_KWARGS,
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
    *,
    analysis_status: str = "ok",
    analysis_error: str | None = None,
) -> FileReport:
    counts = Counter(field.key for field in fields)
    for field in fields:
        if counts[field.key] > 1:
            group = field.exiftool_tag.split(":", 1)[0]
            if not field.label.endswith(f"({group})"):
                field.label = f"{field.label} ({group})"
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
        analysis_status=analysis_status,
        analysis_error=analysis_error,
    )


def _append_warning_once(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


FILESYSTEM_DATE_KEYS: frozenset[str] = frozenset({"FileModifyDate", "FileAccessDate", "FileCreateDate"})


def residual_sensitive_fields(report: FileReport) -> list[MetaField]:
    """Sensitive, removable fields still present in *report* (excludes OS timestamps)."""

    return [
        field
        for field in report.fields
        if field.is_sensitive and not field.is_computed and field.key not in FILESYSTEM_DATE_KEYS
    ]


def verify(path: Path) -> list[MetaField]:
    """Re-read *path* and return sensitive fields that survived sanitisation.

    Raises :class:`MetadataAnalysisError` when the file could not be read fully:
    an unreadable file must never be reported as verified clean.
    """

    report = analyze(path)
    if report.analysis_status != "ok":
        raise MetadataAnalysisError(report.analysis_error or "Metadata could not be read completely.")
    return residual_sensitive_fields(report)


def analyze(path: Path) -> FileReport:
    """Read metadata from *path* and return a structured report."""

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    file_type = detect_file_type(file_path)
    suffix = file_path.suffix.lower()
    warnings = _report_warnings(file_path)

    def report_with(
        fields: list[MetaField],
        thumbnail: bytes | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> FileReport:
        if status != "ok":
            _append_warning_once(warnings, ANALYSIS_LIMITED_WARNING)
        return _build_report(
            file_path,
            file_type,
            fields,
            thumbnail,
            warnings,
            analysis_status=status,
            analysis_error=error,
        )

    if suffix in IMAGE_SUFFIXES:
        status = "ok"
        error: str | None = None
        try:
            fields = _analyze_with_exiftool(file_path)
        except Exception as exc:
            logging.warning("exiftool image read failed for %s: %s", file_path, exc)
            try:
                fields = _analyze_image_fallback(file_path)
                status = "partial"
                error = f"exiftool read failed: {exc}"
            except Exception:
                logging.exception("Failed to analyze image: %s", file_path)
                fields = []
                status = "unverified"
                error = f"Metadata could not be read: {exc}"
                _append_warning_once(warnings, IMAGE_PARSE_WARNING)

        thumbnail = None
        try:
            thumbnail = _extract_thumbnail(file_path)
            if thumbnail is None and suffix in {".jpg", ".jpeg", ".tiff", ".tif", ".webp"}:
                with Image.open(file_path) as image:
                    preview = image.copy()
                    preview.thumbnail((256, 256))
                    buffer = io.BytesIO()
                    preview.save(buffer, format="JPEG")
                    thumbnail = buffer.getvalue()
        except Exception:
            logging.exception("Failed to build image thumbnail: %s", file_path)
            _append_warning_once(warnings, IMAGE_THUMBNAIL_WARNING)

        return report_with(fields, thumbnail, status, error)

    if suffix in PDF_SUFFIXES:
        try:
            fields, status, error, pdf_warnings = _analyze_pdf(file_path)
            for msg in pdf_warnings:
                _append_warning_once(warnings, msg)
        except Exception as exc:
            logging.exception("Failed to analyze PDF: %s", file_path)
            fields, status, error = [], "unverified", f"Metadata could not be read: {exc}"
        return report_with(fields, status=status, error=error)

    if suffix in DOC_SUFFIXES:
        try:
            fields, status, error = _analyze_docx(file_path)
        except Exception as exc:
            logging.exception("Failed to analyze DOCX: %s", file_path)
            fields, status, error = [], "unverified", f"Metadata could not be read: {exc}"
        return report_with(fields, status=status, error=error)

    if suffix in VIDEO_SUFFIXES:
        try:
            fields = _analyze_with_exiftool(file_path)
            return report_with(fields)
        except Exception as exc:
            logging.warning("exiftool video read failed for %s: %s", file_path, exc)
            return report_with([], status="unverified", error=f"Metadata could not be read: {exc}")

    try:
        fields = _analyze_with_exiftool(file_path)
        return report_with(fields)
    except Exception as exc:
        logging.warning("exiftool read failed for %s: %s", file_path, exc)
        return report_with([], status="unverified", error=f"Metadata could not be read: {exc}")
