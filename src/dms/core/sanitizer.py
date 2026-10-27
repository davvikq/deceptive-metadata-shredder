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

import piexif
from docx import Document
from lxml import etree
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from dms.config import require_exiftool
from dms.core.exiftool_tags import validate_exif_tag
from dms.core.models import FileReport
from dms.core.utils import EXIFTOOL_TIMEOUT, get_subprocess_flags, remove_exiftool_signature

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
        timeout=EXIFTOOL_TIMEOUT,
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
            timeout=EXIFTOOL_TIMEOUT,
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
    if destination.suffix.lower() in {".jpg", ".jpeg"}:
        try:
            piexif.remove(str(destination))
            return
        except Exception as exc:
            logging.warning(
                "piexif EXIF removal failed for %s (%s); falling back to Pillow re-encode",
                destination.name,
                exc,
            )
    with Image.open(destination) as image:
        clean = image.copy()
        clean.info.pop("exif", None)
        clean.save(destination)


def _sanitize_pdf(destination: Path) -> None:
    """Rewrite a PDF while preserving document content and dropping authorship."""
    # ExifTool updates PDFs incrementally: -all= can leave old /Info and XMP
    # bytes in the file. Clone the full document into a fresh PDF so outlines,
    # forms and attachments survive, then empty XMP streams before unlinking.
    fd, rewritten_str = tempfile.mkstemp(prefix=".dms_pdf_", suffix=".pdf", dir=destination.parent)
    rewritten = Path(rewritten_str)
    try:
        with os.fdopen(fd, "wb") as output, destination.open("rb") as source:
            reader = PdfReader(source)
            writer = PdfWriter()
            writer.clone_document_from_reader(reader)
            writer.metadata = None
            writer.xmp_metadata = b""
            writer.xmp_metadata = None
            for page in writer.pages:
                page_metadata = page.get("/Metadata")
                if page_metadata is not None:
                    page_metadata.get_object().set_data(b"")
                    del page[NameObject("/Metadata")]
                for reference in page.get("/Annots", []):
                    annotation = reference.get_object()
                    if annotation.get("/Subtype") != "/Widget":
                        annotation.pop(NameObject("/T"), None)
                        annotation.pop(NameObject("/M"), None)
                        annotation.pop(NameObject("/CreationDate"), None)
            writer.write(output)
        os.replace(rewritten, destination)
    finally:
        rewritten.unlink(missing_ok=True)


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


def _sanitize_docx(destination: Path) -> None:
    """Clear OOXML properties and revision/comment attribution."""
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

        # Document properties and revision/comment authors live in different
        # OOXML parts. Clearing only python-docx core_properties misses them.
        for properties_name in ("core.xml", "custom.xml", "app.xml"):
            properties_xml = extract_root / "docProps" / properties_name
            if properties_xml.exists():
                tree = etree.parse(str(properties_xml), parser=etree.XMLParser(resolve_entities=False, no_network=True))
                tree.getroot().clear()
                tree.write(str(properties_xml), encoding="UTF-8", xml_declaration=True)

        word_root = extract_root / "word"
        for xml_path in word_root.rglob("*.xml"):
            tree = etree.parse(str(xml_path), parser=etree.XMLParser(resolve_entities=False, no_network=True))
            changed = False
            for element in tree.iter():
                for attribute in list(element.attrib):
                    if etree.QName(attribute).localname.lower() in {"author", "initials", "userid", "providerid", "email"}:
                        del element.attrib[attribute]
                        changed = True
            if changed:
                tree.write(str(xml_path), encoding="UTF-8", xml_declaration=True)

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
        if suffix == ".pdf":
            _sanitize_pdf(staging)
            return
        if suffix == ".docx":
            _sanitize_docx(staging)
            return
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
