"""Metadata removal helpers."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from docx import Document
from PIL import Image
from pypdf import PdfReader, PdfWriter

from dms.config import require_exiftool
from dms.core.exiftool_tags import validate_exif_tag
from dms.core.models import FileReport
from dms.core.utils import get_subprocess_flags, remove_exiftool_signature

INTERRUPT_LOG = "Process interrupted. Original file %s remains unchanged."

# Reject obviously truncated outputs (metadata edits rarely shrink the payload this much).
_ATOMIC_MIN_ABSOLUTE = 256
_ATOMIC_RATIO_FLOOR = 0.05


def _safe_extractall(archive: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract ZIP members while preventing ZipSlip path traversal."""
    resolved_target = target_dir.resolve()
    for member in archive.infolist():
        member_path = (resolved_target / member.filename).resolve()
        try:
            member_path.relative_to(resolved_target)
        except ValueError:
            raise ValueError(f"Path traversal detected in ZIP entry: {member.filename}")
    archive.extractall(target_dir)


def build_output_path(path: Path, output_path: Path | None = None) -> Path:
    """Return the destination path for a cleaned copy."""

    if output_path:
        return output_path
    return path.with_name(f"{path.stem}_cleaned{path.suffix}")


def _validate_atomic_output(source_size: int, result_path: Path) -> None:
    """Ensure the processed file is not empty or implausibly truncated."""

    result_size = result_path.stat().st_size
    if result_size == 0:
        raise RuntimeError("Refusing to replace destination: processed file is empty.")
    if source_size == 0:
        return
    if source_size >= _ATOMIC_MIN_ABSOLUTE and result_size < _ATOMIC_MIN_ABSOLUTE:
        raise RuntimeError("Refusing to replace destination: processed file is implausibly small.")
    ratio = result_size / source_size
    if source_size >= 4096 and ratio < _ATOMIC_RATIO_FLOOR:
        raise RuntimeError("Refusing to replace destination: processed file lost most of the data.")


def run_atomic_file_update(
    source: Path,
    target: Path,
    mutate: Callable[[Path], None],
    *,
    interrupt_check: Callable[[], bool] | None = None,
    protected_path_for_log: Path | None = None,
) -> None:
    """Copy *source* to a same-directory temp file, run *mutate*, validate, atomically replace *target*.

    The temp file lives in ``target.parent`` so ``os.replace`` is a single filesystem operation.
    On failure or interruption before replace, *target* is left unchanged (or absent if it never existed).
    """

    log_path = protected_path_for_log or source
    target.parent.mkdir(parents=True, exist_ok=True)
    source_size = source.stat().st_size

    fd, staging_str = tempfile.mkstemp(prefix=".dms_atomic_", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    staging: Path | None = Path(staging_str)
    try:
        shutil.copy2(source, staging)
        if interrupt_check and interrupt_check():
            logging.warning(INTERRUPT_LOG, log_path)
            raise RuntimeError("Operation interrupted before metadata processing.")

        mutate(staging)

        if interrupt_check and interrupt_check():
            logging.warning(INTERRUPT_LOG, log_path)
            raise RuntimeError("Operation interrupted before committing.")

        _validate_atomic_output(source_size, staging)
        os.replace(staging, target)
        staging = None
    except KeyboardInterrupt:
        logging.warning(INTERRUPT_LOG, log_path)
        raise
    finally:
        if staging is not None:
            try:
                staging.unlink(missing_ok=True)
            except OSError as exc:
                logging.debug("Could not remove staging file %s: %s", staging, exc)


def _resolve_edit_destination_path(source: Path, output_path: Path | None = None) -> Path:
    """Return the final path for an edit without copying files."""

    if output_path:
        return Path(output_path)
    if source.stem.endswith("_cleaned"):
        return source
    return build_output_path(source)


def _sanitize_with_exiftool(destination: Path) -> None:
    exiftool = require_exiftool()
    subprocess.run(
        [exiftool, "-overwrite_original_in_place", "-all=", str(destination)],
        check=True,
        capture_output=True,
        text=True,
        creationflags=get_subprocess_flags(),
    )


def remove_field(
    file_report_or_path: FileReport | Path,
    original_tag_name: str,
    output_path: Path | None = None,
    *,
    interrupt_check: Callable[[], bool] | None = None,
) -> Path:
    """Remove a single metadata field from a copied file."""

    source = file_report_or_path.path if isinstance(file_report_or_path, FileReport) else Path(file_report_or_path)
    destination = _resolve_edit_destination_path(source, output_path)
    exiftool_path = require_exiftool()
    safe_tag = validate_exif_tag(original_tag_name)

    def mutate(staging: Path) -> None:
        result = subprocess.run(
            [
                exiftool_path,
                f"-{safe_tag}=",
                "-overwrite_original",
                str(staging),
            ],
            capture_output=True,
            text=True,
            creationflags=get_subprocess_flags(),
        )
        stderr = (result.stderr or "").strip()
        warning_markers = [
            "Can't delete FileModifyDate",
            "Can't delete FileAccessDate",
            "Can't delete FileCreateDate",
            "Nothing to do",
        ]
        if any(marker in stderr for marker in warning_markers):
            remove_exiftool_signature(staging, exiftool_path)
            return
        if result.returncode != 0:
            raise RuntimeError(stderr or "Failed to remove metadata field.")
        remove_exiftool_signature(staging, exiftool_path)

    run_atomic_file_update(
        source,
        destination,
        mutate,
        interrupt_check=interrupt_check,
        protected_path_for_log=source,
    )
    return destination


def _sanitize_image_without_exiftool(destination: Path) -> None:
    with Image.open(destination) as image:
        clean = image.copy()
        clean.info.pop("exif", None)
        clean.save(destination)


def _sanitize_pdf_without_exiftool(destination: Path) -> None:
    reader = PdfReader(str(destination))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({})
    try:
        writer.xmp_metadata = None
    except AttributeError:
        logging.warning(
            "pypdf API changed (xmp_metadata); XMP metadata may not be fully removed from %s",
            destination.name,
        )
    with destination.open("wb") as handle:
        writer.write(handle)


def _strip_docx_tracked_changes(document_xml: Path) -> None:
    """Replace w:ins/w:del wrappers with their children, preserving other tags."""

    try:
        root = ET.fromstring(document_xml.read_text(encoding="utf-8"))
    except ET.ParseError:
        logging.warning("Could not parse DOCX XML for tracked-change cleanup: %s", document_xml)
        return

    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    tracked_tags = {f"{ns}ins", f"{ns}del"}

    def unwrap(parent: ET.Element) -> None:
        for child in list(parent):
            unwrap(child)
            if child.tag in tracked_tags:
                index = list(parent).index(child)
                parent.remove(child)
                for grandchild in list(child):
                    parent.insert(index, grandchild)
                    index += 1

    unwrap(root)
    document_xml.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")


def _sanitize_docx_without_exiftool(destination: Path) -> None:
    document = Document(str(destination))
    props = document.core_properties
    props.author = ""
    props.last_modified_by = ""
    try:
        props.company = ""
    except AttributeError:
        pass
    props.comments = ""
    props.subject = ""
    props.title = ""
    document.save(destination)

    with tempfile.TemporaryDirectory() as tmp_dir:
        extract_root = Path(tmp_dir)
        with zipfile.ZipFile(destination) as archive:
            _safe_extractall(archive, extract_root)

        document_xml = extract_root / "word" / "document.xml"
        if document_xml.exists():
            _strip_docx_tracked_changes(document_xml)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in extract_root.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(extract_root).as_posix()
                    info = zipfile.ZipInfo(arcname)
                    info.date_time = (1980, 1, 1, 0, 0, 0)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, item.read_bytes())


def repack_docx_zip_dates(
    destination: Path,
    date_time: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0),
) -> None:
    """Rewrite ZIP entry timestamps in an OOXML file to hide the real operation time."""

    with tempfile.TemporaryDirectory() as tmp_dir:
        extract_root = Path(tmp_dir)
        with zipfile.ZipFile(destination) as archive:
            _safe_extractall(archive, extract_root)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in extract_root.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(extract_root).as_posix()
                    info = zipfile.ZipInfo(arcname)
                    info.date_time = date_time
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, item.read_bytes())


def remove_all(
    file_report_or_path: FileReport | Path,
    output_path: Path | None = None,
    *,
    interrupt_check: Callable[[], bool] | None = None,
) -> Path:
    """Create a cleaned copy of the file with metadata removed."""

    source = file_report_or_path.path if isinstance(file_report_or_path, FileReport) else Path(file_report_or_path)
    destination = build_output_path(source, output_path)
    suffix = source.suffix.lower()

    def mutate(staging: Path) -> None:
        try:
            _sanitize_with_exiftool(staging)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            logging.warning("exiftool sanitization failed for %s, trying fallback: %s", staging.name, exc)
            if suffix in {".jpg", ".jpeg", ".png"}:
                _sanitize_image_without_exiftool(staging)
                logging.info(
                    "Fallback sanitization (Pillow) used for %s — verify metadata was fully removed",
                    staging.name,
                )
                return
            if suffix == ".pdf":
                _sanitize_pdf_without_exiftool(staging)
                logging.info(
                    "Fallback sanitization (pypdf) used for %s — verify metadata was fully removed",
                    staging.name,
                )
                return
            if suffix == ".docx":
                _sanitize_docx_without_exiftool(staging)
                logging.info(
                    "Fallback sanitization (python-docx) used for %s — verify metadata was fully removed",
                    staging.name,
                )
                return
            raise RuntimeError("This file type requires exiftool for sanitization.") from exc

    run_atomic_file_update(
        source,
        destination,
        mutate,
        interrupt_check=interrupt_check,
        protected_path_for_log=source,
    )
    return destination


def resolve_spoof_destination(path: Path) -> Path:
    """Path where the spoofed/cleaned working copy should land (no I/O)."""

    if path.stem.endswith("_cleaned"):
        return path
    return build_output_path(path)
