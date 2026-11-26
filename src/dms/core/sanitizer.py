"""Metadata removal helpers."""

from __future__ import annotations

import logging
import os
import random
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import piexif
from docx import Document
from lxml import etree
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from dms.config import require_exiftool
from dms.core.exiftool_tags import validate_exif_tag
from dms.core.models import FileReport
from dms.core.utils import EXIFTOOL_TEXT_KWARGS, EXIFTOOL_TIMEOUT, get_subprocess_flags, remove_exiftool_signature

INTERRUPT_LOG = "Process interrupted. Original file %s remains unchanged."


class OutputPathError(ValueError):
    """Raised when an output path would overwrite the source file."""


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
    # Small files (icons, tiny WebP) can legitimately shrink below 256 bytes.
    if source_size >= 4096 and result_size < _ATOMIC_MIN_ABSOLUTE:
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


def _clear_residual_sensitive_tags(destination: Path, exiftool: str) -> None:
    """Second pass for formats where -all= cannot delete a container (e.g. TIFF IFD0)."""

    from dms.core.analyzer import FILESYSTEM_DATE_KEYS, analyze

    try:
        report = analyze(destination)
    except Exception as exc:
        logging.warning("Residual metadata analysis failed for %s: %s", destination, exc)
        return
    clears: list[str] = []
    for field in report.fields:
        if not field.is_sensitive or field.is_computed or field.key in FILESYSTEM_DATE_KEYS:
            continue
        try:
            safe_tag = validate_exif_tag(field.exiftool_tag)
        except ValueError:
            continue
        clears.append(f"-{safe_tag}=")
    if not clears:
        return
    result = subprocess.run(
        [exiftool, "-m", "-overwrite_original_in_place", *dict.fromkeys(clears), str(destination)],
        capture_output=True,
        check=False,
        timeout=EXIFTOOL_TIMEOUT,
        creationflags=get_subprocess_flags(),
        **EXIFTOOL_TEXT_KWARGS,
    )
    if result.returncode != 0:
        logging.warning(
            "Residual metadata cleanup failed for %s: %s",
            destination,
            (result.stderr or "").strip(),
        )


def _sanitize_with_exiftool(destination: Path) -> None:
    exiftool = require_exiftool()
    args = [exiftool, "-overwrite_original_in_place", "-all="]
    if destination.suffix.lower() in {".mp4", ".mov"}:
        # QuickTime mvhd/tkhd/mdhd timestamps cannot be deleted with -all=; zero them.
        args.extend(
            [
                "-m",
                "-QuickTime:CreateDate=0000:00:00 00:00:00",
                "-QuickTime:ModifyDate=0000:00:00 00:00:00",
                "-QuickTime:TrackCreateDate=0000:00:00 00:00:00",
                "-QuickTime:TrackModifyDate=0000:00:00 00:00:00",
                "-QuickTime:MediaCreateDate=0000:00:00 00:00:00",
                "-QuickTime:MediaModifyDate=0000:00:00 00:00:00",
            ]
        )
    args.append(str(destination))
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        timeout=EXIFTOOL_TIMEOUT,
        creationflags=get_subprocess_flags(),
        **EXIFTOOL_TEXT_KWARGS,
    )
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        raise RuntimeError(stderr or "exiftool sanitization failed.")
    if "can't delete" in stderr.lower():
        _clear_residual_sensitive_tags(destination, exiftool)


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
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
            **EXIFTOOL_TEXT_KWARGS,
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
    suffix = destination.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
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
        icc_profile = image.info.get("icc_profile")
        if suffix in {".jpg", ".jpeg"}:
            clean = ImageOps.exif_transpose(image)
            if clean.mode not in {"RGB", "L", "CMYK"}:
                clean = clean.convert("RGB")
            save_kwargs: dict[str, object] = {
                "format": "JPEG",
                "quality": 95,
                "subsampling": 0,
            }
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
            clean.save(destination, **save_kwargs)
            return
        if suffix == ".png":
            dpi = image.info.get("dpi")
            clean = image.copy()
            save_kwargs = {"format": "PNG"}
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
            if dpi:
                save_kwargs["dpi"] = dpi
            clean.save(destination, **save_kwargs)
            return
        clean = image.copy()
        clean.info.pop("exif", None)
        clean.save(destination)


def _purge_pdf_object(obj: object, seen: set[int], protected_ids: set[int]) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

    if isinstance(obj, IndirectObject):
        if obj.idnum in seen or obj.idnum in protected_ids:
            return
        seen.add(obj.idnum)
        _purge_pdf_object(obj.get_object(), seen, protected_ids)
        return
    if isinstance(obj, StreamObject):
        obj.set_data(b"")
        for key in list(obj.keys()):
            if str(key) in {"/P", "/Parent"}:
                continue
            _purge_pdf_object(obj.raw_get(key), seen, protected_ids)
        obj.clear()
    elif isinstance(obj, DictionaryObject):
        for key in list(obj.keys()):
            if str(key) in {"/P", "/Parent"}:
                continue
            _purge_pdf_object(obj.raw_get(key), seen, protected_ids)
        obj.clear()
    elif isinstance(obj, ArrayObject):
        for item in list(obj):
            _purge_pdf_object(item, seen, protected_ids)
        obj.clear()


def _sanitize_pdf(
    destination: Path,
    *,
    strip_annotations: bool = False,
    strip_attachments: bool = False,
) -> None:
    """Rewrite a PDF while preserving document content and dropping authorship."""
    # ExifTool updates PDFs incrementally: -all= can leave old /Info and XMP
    # bytes in the file. Clone the full document into a fresh PDF so outlines,
    # forms and attachments survive unless explicitly stripped, then empty XMP
    # streams before unlinking.
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
            purged_ids: set[int] = set()
            protected_ids: set[int] = {
                page.indirect_reference.idnum
                for page in writer.pages
                if page.indirect_reference is not None
            }
            if getattr(writer._root_object, "indirect_reference", None) is not None:
                protected_ids.add(writer._root_object.indirect_reference.idnum)
            if strip_annotations:
                for page in writer.pages:
                    if "/Annots" in page:
                        _purge_pdf_object(page.raw_get("/Annots"), purged_ids, protected_ids)
                writer.remove_annotations(None)
            elif strip_attachments:
                for page in writer.pages:
                    annots = page.get("/Annots") or []
                    for ref in annots:
                        annot = ref.get_object()
                        if annot.get("/Subtype") == "/FileAttachment":
                            _purge_pdf_object(ref, purged_ids, protected_ids)
                writer.remove_annotations("/FileAttachment")
            if strip_attachments:
                root = writer._root_object
                names = root.get("/Names")
                if names is not None:
                    names_obj = names.get_object()
                    if hasattr(names_obj, "pop"):
                        embedded = names_obj.pop(NameObject("/EmbeddedFiles"), None)
                        if embedded is not None:
                            _purge_pdf_object(embedded, purged_ids, protected_ids)
                        if not names_obj:
                            root.pop(NameObject("/Names"), None)
                af_root = root.pop(NameObject("/AF"), None)
                if af_root is not None:
                    _purge_pdf_object(af_root, purged_ids, protected_ids)
            for page in writer.pages:
                page_metadata = page.get("/Metadata")
                if page_metadata is not None:
                    page_metadata.get_object().set_data(b"")
                    del page[NameObject("/Metadata")]
                if strip_annotations:
                    page.pop(NameObject("/Annots"), None)
                else:
                    for reference in page.get("/Annots", []):
                        annotation = reference.get_object()
                        if annotation.get("/Subtype") != "/Widget":
                            annotation.pop(NameObject("/T"), None)
                            annotation.pop(NameObject("/M"), None)
                            annotation.pop(NameObject("/CreationDate"), None)
                if strip_attachments:
                    af_page = page.pop(NameObject("/AF"), None)
                    if af_page is not None:
                        _purge_pdf_object(af_page, purged_ids, protected_ids)
            writer.write(output)
        os.replace(rewritten, destination)
    finally:
        rewritten.unlink(missing_ok=True)


def _strip_docx_tracked_changes(document_xml: Path) -> None:
    """Accept insertions, drop deletions, and remove all revision wrappers."""

    try:
        root = ET.fromstring(document_xml.read_text(encoding="utf-8"))
    except ET.ParseError:
        logging.warning("Could not parse DOCX XML for tracked-change cleanup: %s", document_xml)
        return

    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    inserted_tags = {f"{ns}ins", f"{ns}moveTo"}
    deleted_tags = {f"{ns}del", f"{ns}moveFrom"}
    deleted_content_tags = {f"{ns}delText", f"{ns}delInstrText"}

    def clean_children(parent: ET.Element) -> None:
        kept: list[ET.Element] = []
        for child in list(parent):
            if child.tag in deleted_tags:
                # Deleted/moved-away revisions must disappear completely.
                continue
            if child.tag in inserted_tags:
                clean_children(child)
                kept.extend(list(child))
                continue
            clean_children(child)
            if child.tag in deleted_content_tags:
                continue
            kept.append(child)
        for child in list(parent):
            parent.remove(child)
        parent.extend(kept)

    clean_children(root)
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

        word_root = extract_root / "word"
        tracked_change_parts = [
            word_root / "document.xml",
            word_root / "footnotes.xml",
            word_root / "endnotes.xml",
            *sorted(word_root.glob("header*.xml")),
            *sorted(word_root.glob("footer*.xml")),
        ]
        for xml_path in tracked_change_parts:
            if xml_path.exists():
                _strip_docx_tracked_changes(xml_path)

        # Document properties and revision/comment authors live in different
        # OOXML parts. Clearing only python-docx core_properties misses them.
        for properties_name in ("core.xml", "custom.xml", "app.xml"):
            properties_xml = extract_root / "docProps" / properties_name
            if properties_xml.exists():
                tree = etree.parse(str(properties_xml), parser=etree.XMLParser(resolve_entities=False, no_network=True))
                tree.getroot().clear()
                tree.write(str(properties_xml), encoding="UTF-8", xml_declaration=True)

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

        _write_zip_with_dates(extract_root, destination)


def _random_zip_base_datetime() -> datetime:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    shifted = now - timedelta(days=random.randint(30, 1000))
    return shifted.replace(
        hour=random.randint(9, 18),
        minute=random.randint(0, 59),
        second=random.randrange(0, 60, 2),
        microsecond=0,
    )


def _to_dos_zip_tuple(dt: datetime) -> tuple[int, int, int, int, int, int]:
    year = max(dt.year, 1980)
    second = dt.second & ~1
    return (year, dt.month, dt.day, dt.hour, dt.minute, second)


def _write_zip_with_dates(
    extract_root: Path,
    destination: Path,
    date_time: tuple[int, int, int, int, int, int] | None = None,
    *,
    stagger: bool = True,
) -> None:
    if date_time is None:
        base = _random_zip_base_datetime()
    else:
        base = datetime(
            max(date_time[0], 1980),
            date_time[1],
            date_time[2],
            date_time[3],
            date_time[4],
            date_time[5] & ~1,
        )
    offset = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(extract_root.rglob("*")):
            if not item.is_file():
                continue
            arcname = item.relative_to(extract_root).as_posix()
            info = zipfile.ZipInfo(arcname)
            entry_dt = base + timedelta(seconds=offset) if stagger else base
            info.date_time = _to_dos_zip_tuple(entry_dt)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, item.read_bytes())
            if stagger:
                offset += random.choice((2, 4, 6))


def repack_docx_zip_dates(
    destination: Path,
    date_time: tuple[int, int, int, int, int, int] | None = None,
    *,
    stagger: bool = True,
) -> None:
    """Rewrite ZIP entry timestamps in an OOXML file to hide the real operation time."""

    with tempfile.TemporaryDirectory() as tmp_dir:
        extract_root = Path(tmp_dir)
        with zipfile.ZipFile(destination) as archive:
            _safe_extractall(archive, extract_root)
        _write_zip_with_dates(extract_root, destination, date_time, stagger=stagger)


def remove_all(
    file_report_or_path: FileReport | Path,
    output_path: Path | None = None,
    *,
    interrupt_check: Callable[[], bool] | None = None,
    strip_annotations: bool = False,
    strip_attachments: bool = False,
) -> Path:
    """Create a cleaned copy of the file with metadata removed."""

    source = file_report_or_path.path if isinstance(file_report_or_path, FileReport) else Path(file_report_or_path)
    destination = build_output_path(source, output_path)
    suffix = source.suffix.lower()

    def mutate(staging: Path) -> None:
        if suffix == ".pdf":
            _sanitize_pdf(
                staging,
                strip_annotations=strip_annotations,
                strip_attachments=strip_attachments,
            )
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
