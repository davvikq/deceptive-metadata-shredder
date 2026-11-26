from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import pytest
from docx import Document
from lxml import etree
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import NameObject, TextStringObject
from dms.core.analyzer import analyze
from dms.core.sanitizer import _safe_extractall, _strip_docx_tracked_changes, remove_all


FIXTURES = Path(__file__).parent / "fixtures"


def test_cleaned_copy_is_created_without_touching_original(tmp_path) -> None:
    source = FIXTURES / "test_no_meta.png"
    output = tmp_path / "cleaned.png"

    result = remove_all(source, output)

    assert result.exists()
    assert source.exists()
    assert source.read_bytes() == (FIXTURES / "test_no_meta.png").read_bytes()
    remaining = [
        field
        for field in analyze(result).fields
        if field.key != "SourceFile" and not field.exiftool_tag.startswith("System:")
    ]

    assert not any(field.is_sensitive for field in remaining)


def test_pdf_cleanup_removes_info_xmp_and_previous_author_bytes(tmp_path) -> None:
    source = tmp_path / "authored.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_outline_item("Chapter", 0)
    writer.add_attachment(filename="note.txt", data=b"keep this attachment")
    annotation = Text(rect=(20, 20, 40, 40), text="Keep this note")
    annotation[NameObject("/T")] = TextStringObject("Private Nick")
    writer.add_annotation(page_number=0, annotation=annotation)
    writer.add_metadata({"/Author": "Private Nick", "/Creator": "Private Nick"})
    writer.xmp_metadata = b"<metadata>Private Nick</metadata>"
    writer.write(source)

    cleaned = remove_all(source)
    report = analyze(cleaned)
    reader = PdfReader(cleaned)

    assert source.read_bytes() != cleaned.read_bytes()
    assert b"Private Nick" not in cleaned.read_bytes()
    assert reader.metadata is None
    assert reader.xmp_metadata is None
    assert len(reader.pages) == 1
    assert len(reader.outline) == 1
    assert reader.attachments["note.txt"] == [b"keep this attachment"]
    saved_annotation = reader.pages[0]["/Annots"][0].get_object()
    assert "/T" not in saved_annotation
    assert saved_annotation["/Contents"] == "Keep this note"
    assert not {"Author", "Creator"} & {field.key for field in report.fields}


def test_pdf_fixture_author_is_absent_after_reanalysis(tmp_path) -> None:
    cleaned = remove_all(FIXTURES / "test_document.pdf", tmp_path / "document_cleaned.pdf")

    assert b"Jane Doe" not in cleaned.read_bytes()
    assert not {"Author", "Creator", "Producer"} & {field.key for field in analyze(cleaned).fields}


def test_docx_cleanup_removes_author_from_properties_and_comments(tmp_path) -> None:
    source = tmp_path / "authored.docx"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    app_ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
    with zipfile.ZipFile(FIXTURES / "test_document.docx") as original, zipfile.ZipFile(source, "w") as authored:
        for info in original.infolist():
            payload = original.read(info.filename)
            if info.filename in {"_rels/.rels", "word/_rels/document.xml.rels", "[Content_Types].xml", "docProps/app.xml"}:
                root = etree.fromstring(payload)
                if info.filename == "_rels/.rels":
                    etree.SubElement(root, f"{{{rel_ns}}}Relationship", Id="rIdCustom", Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties", Target="docProps/custom.xml")
                elif info.filename == "word/_rels/document.xml.rels":
                    etree.SubElement(root, f"{{{rel_ns}}}Relationship", Id="rIdComments", Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments", Target="comments.xml")
                elif info.filename == "[Content_Types].xml":
                    etree.SubElement(root, f"{{{content_ns}}}Override", PartName="/docProps/custom.xml", ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml")
                    etree.SubElement(root, f"{{{content_ns}}}Override", PartName="/word/comments.xml", ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
                else:
                    etree.SubElement(root, f"{{{app_ns}}}Company").text = "Private Nick"
                payload = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
            authored.writestr(info, payload)
        authored.writestr("docProps/custom.xml", '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"><property name="Owner"><value>Private Nick</value></property></Properties>')
        authored.writestr("word/comments.xml", '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="0" w:author="Private Nick" w:initials="PN"><w:p><w:r><w:t>Keep this note</w:t></w:r></w:p></w:comment></w:comments>')

    cleaned = remove_all(source)
    report = analyze(cleaned)

    assert Document(cleaned).paragraphs[0].text == Document(source).paragraphs[0].text
    assert not {"Author", "Creator", "LastModifiedBy", "Company"} & {field.key for field in report.fields}
    with zipfile.ZipFile(cleaned) as archive:
        assert b"Private Nick" not in archive.read("docProps/app.xml")
        assert b"Private Nick" not in archive.read("docProps/custom.xml")
        comments = archive.read("word/comments.xml")
        assert b"Private Nick" not in comments
        assert b"Keep this note" in comments


def test_safe_extractall_rejects_path_traversal(tmp_path) -> None:
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", "bad")

    extract_root = tmp_path / "extract"
    extract_root.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="Path traversal detected"):
            _safe_extractall(archive, extract_root)


def test_strip_docx_tracked_changes_keeps_non_tracked_tags(tmp_path) -> None:
    document_xml = tmp_path / "document.xml"
    document_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:ins><w:r><w:t>Inserted</w:t></w:r></w:ins>
      <w:instrText>DO_NOT_TOUCH</w:instrText>
      <w:del><w:r><w:delText>Deleted</w:delText></w:r></w:del>
    </w:p>
  </w:body>
</w:document>
""",
        encoding="utf-8",
    )

    _strip_docx_tracked_changes(document_xml)
    transformed = document_xml.read_text(encoding="utf-8")
    root = ET.fromstring(transformed)
    local_names = [element.tag.split("}")[-1] for element in root.iter()]

    assert "ins" not in local_names
    assert "del" not in local_names
    assert "delText" not in local_names
    assert "Deleted" not in transformed
    assert "Inserted" in transformed
    assert "instrText" in local_names
    assert "DO_NOT_TOUCH" in transformed


def test_cleaned_docx_does_not_keep_deleted_revision_text(tmp_path) -> None:
    source = tmp_path / "tracked.docx"
    source.write_bytes((FIXTURES / "test_document.docx").read_bytes())

    with zipfile.ZipFile(source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    document_xml = entries["word/document.xml"].decode("utf-8")
    injected = (
        '<w:p><w:r><w:t>BEFORE</w:t></w:r>'
        '<w:ins w:id="1" w:author="A"><w:r><w:t>INSERTED_SECRET</w:t></w:r></w:ins>'
        '<w:del w:id="2" w:author="A"><w:r><w:delText>DELETED_SECRET</w:delText></w:r></w:del>'
        "</w:p>"
    )
    assert "</w:body>" in document_xml
    entries["word/document.xml"] = document_xml.replace("</w:body>", injected + "</w:body>", 1).encode("utf-8")
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)

    cleaned = remove_all(source)

    with zipfile.ZipFile(cleaned) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
    ET.fromstring(body)
    assert "DELETED_SECRET" not in body
    assert "delText" not in body
    assert "INSERTED_SECRET" in body


def test_clean_tiff_removes_stubborn_ifd0_tags(tmp_path) -> None:
    source = tmp_path / "photo.tiff"
    source.write_bytes((FIXTURES / "test_with_metadata.tiff").read_bytes())

    cleaned = remove_all(source)

    fields = analyze(cleaned).by_key()
    assert "Make" not in fields
    assert "Model" not in fields
    assert "Software" not in fields
    assert analyze(cleaned).analysis_status == "ok"


def test_clean_tiny_webp_is_not_rejected_as_truncated(tmp_path) -> None:
    source = tmp_path / "tiny.webp"
    source.write_bytes((FIXTURES / "test_with_metadata.webp").read_bytes())

    cleaned = remove_all(source)

    assert cleaned.exists()
    assert cleaned.stat().st_size > 0
    assert analyze(cleaned).by_key().get("Make") is None
    assert analyze(cleaned).analysis_status == "ok"


def test_pdf_strip_annotations_and_attachments_removes_content(tmp_path) -> None:
    source = tmp_path / "legal.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_attachment(filename="secret.txt", data=b"attachment-secret")
    annotation = Text(rect=(20, 20, 40, 40), text="PII_IN_ANNOTATION")
    annotation[NameObject("/T")] = TextStringObject("Lawyer Name")
    writer.add_annotation(page_number=0, annotation=annotation)
    writer.add_metadata({"/Author": "Lawyer Name"})
    writer.write(source)

    stripped = remove_all(
        source,
        tmp_path / "legal_stripped.pdf",
        strip_annotations=True,
        strip_attachments=True,
    )
    reader = PdfReader(stripped)
    raw_bytes = stripped.read_bytes()

    assert b"PII_IN_ANNOTATION" not in raw_bytes
    assert b"attachment-secret" not in raw_bytes
    assert b"Lawyer Name" not in raw_bytes
    assert reader.pages[0].get("/Annots") is None
    assert reader.attachments == {}


def test_docx_clean_uses_plausible_staggered_zip_dates(tmp_path) -> None:
    cleaned = remove_all(FIXTURES / "test_document.docx", tmp_path / "doc_cleaned.docx")

    with zipfile.ZipFile(cleaned) as archive:
        timestamps = [info.date_time for info in archive.infolist()]

    assert timestamps
    assert not all(ts == (1980, 1, 1, 0, 0, 0) for ts in timestamps)
    assert all(ts[0] >= 2000 for ts in timestamps)
    assert len(set(timestamps)) > 1


def test_pillow_jpeg_fallback_strips_icc_by_default_and_preserves_orientation(tmp_path, monkeypatch) -> None:
    import piexif
    from PIL import Image
    from dms.core import sanitizer

    source = tmp_path / "rotated.jpg"
    img = Image.new("RGB", (40, 20), color=(120, 180, 60))
    icc = b"dummy-icc-profile-bytes"
    exif_bytes = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6, piexif.ImageIFD.Make: b"Canon"}})
    img.save(source, format="JPEG", quality=95, exif=exif_bytes, icc_profile=icc)

    monkeypatch.setattr(sanitizer.piexif, "remove", lambda _p: (_ for _ in ()).throw(RuntimeError("piexif broken")))
    sanitizer._sanitize_image_without_exiftool(source)

    with Image.open(source) as result:
        assert result.size == (20, 40)
        assert "icc_profile" not in result.info
        assert not result.getexif()

    img.save(source, format="JPEG", quality=95, exif=exif_bytes, icc_profile=icc)
    sanitizer._sanitize_image_without_exiftool(source, strip_icc=False)
    with Image.open(source) as result:
        assert result.info.get("icc_profile") == icc


def test_pillow_png_fallback_strips_text_chunks_and_icc_by_default(tmp_path) -> None:
    from PIL import Image, PngImagePlugin
    from dms.core import sanitizer

    source = tmp_path / "secret.png"
    img = Image.new("RGB", (24, 24), color=(10, 20, 30))
    icc = b"dummy-png-icc"
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("Author", "Secret Author")
    pnginfo.add_text("Comment", "Secret Comment")
    img.save(source, format="PNG", pnginfo=pnginfo, icc_profile=icc)

    sanitizer._sanitize_image_without_exiftool(source)

    with Image.open(source) as result:
        assert "Author" not in result.info
        assert "Comment" not in result.info
        assert "icc_profile" not in result.info
    assert b"Secret Author" not in source.read_bytes()

    img.save(source, format="PNG", pnginfo=pnginfo, icc_profile=icc)
    sanitizer._sanitize_image_without_exiftool(source, strip_icc=False)
    with Image.open(source) as result:
        assert result.info.get("icc_profile") == icc


def test_clean_mp4_zeros_quicktime_dates_and_passes_verify(tmp_path) -> None:
    import struct
    from dms.config import get_exiftool_path
    from dms.core.analyzer import verify

    if not get_exiftool_path():
        pytest.skip("exiftool is required for MP4 sanitization test")

    def box(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I4s", 8 + len(payload), tag) + payload

    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41")
    ctime = 3786825600
    mvhd_data = struct.pack(
        ">IIIIIIH10s36s24sI",
        0,
        ctime,
        ctime,
        1000,
        5000,
        0x00010000,
        0x0100,
        b"\x00" * 10,
        b"\x00" * 36,
        b"\x00" * 24,
        1,
    )
    moov = box(b"moov", box(b"mvhd", mvhd_data))
    mdat = box(b"mdat", b"\x00" * 100)

    source = tmp_path / "clip.mp4"
    source.write_bytes(ftyp + moov + mdat)
    assert verify(source)

    cleaned = remove_all(source, tmp_path / "clip_cleaned.mp4")

    assert verify(cleaned) == []


def test_pdf_clean_strips_annotation_rc_subj_and_popup_author(tmp_path) -> None:
    from pypdf.generic import DictionaryObject

    source = tmp_path / "rich_annot.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    popup = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Popup"),
            NameObject("/T"): TextStringObject("Popup Author"),
            NameObject("/M"): TextStringObject("D:20240101000000"),
        }
    )
    popup_ref = writer._add_object(popup)
    annotation = Text(rect=(20, 20, 40, 40), text="Body text")
    annotation[NameObject("/T")] = TextStringObject("Main Author")
    annotation[NameObject("/Subj")] = TextStringObject("Secret Subject")
    annotation[NameObject("/RC")] = TextStringObject("<p>Rich Author</p>")
    annotation[NameObject("/Popup")] = popup_ref
    writer.add_annotation(page_number=0, annotation=annotation)
    writer.write(source)

    cleaned = remove_all(source, tmp_path / "rich_annot_cleaned.pdf")
    raw = cleaned.read_bytes()
    reader = PdfReader(cleaned)
    saved_annot = reader.pages[0]["/Annots"][0].get_object()
    saved_popup = saved_annot["/Popup"].get_object()

    assert saved_annot["/Contents"] == "Body text"
    for key in ("/T", "/Subj", "/RC", "/M", "/CreationDate"):
        assert key not in saved_annot
    assert "/T" not in saved_popup
    assert "/M" not in saved_popup
    assert b"Rich Author" not in raw
    assert b"Popup Author" not in raw
    assert b"Secret Subject" not in raw


def test_docx_clean_removes_thumbnail_customxml_attached_template_and_media_exif(tmp_path) -> None:
    gps_jpg = FIXTURES / "test_with_gps.jpg"
    prepared = tmp_path / "with_pic.docx"
    doc = Document(str(FIXTURES / "test_document.docx"))
    doc.add_picture(str(gps_jpg))
    doc.save(str(prepared))

    source = tmp_path / "rich.docx"
    overrides = {
        "word/settings.xml": (
            b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:attachedTemplate r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
            b'<w:rsids><w:rsidRoot w:val="00112233"/></w:rsids></w:settings>'
        ),
        "word/people.xml": (
            b'<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
            b'<w15:person w15:author="Secret Person"/></w15:people>'
        ),
    }
    with zipfile.ZipFile(prepared) as original, zipfile.ZipFile(source, "w") as out:
        seen: set[str] = set()
        for info in original.infolist():
            seen.add(info.filename)
            out.writestr(info.filename, overrides.get(info.filename, original.read(info.filename)))
        for name, data in overrides.items():
            if name not in seen:
                out.writestr(name, data)

    cleaned = remove_all(source, tmp_path / "rich_cleaned.docx")

    with zipfile.ZipFile(cleaned) as archive:
        names = set(archive.namelist())
        assert "docProps/thumbnail.jpeg" not in names
        assert not any(n.startswith("customXml/") for n in names)
        assert "word/people.xml" not in names
        settings = archive.read("word/settings.xml").decode("utf-8")
        assert "attachedTemplate" not in settings
        assert "rsids" not in settings
        media_names = [n for n in names if n.startswith("word/media/")]
        assert media_names
        media_img = tmp_path / "extracted.jpg"
        media_img.write_bytes(archive.read(media_names[0]))
        assert "GPSLatitude" not in analyze(media_img).by_key()


def test_docx_zip_bomb_is_rejected(tmp_path) -> None:
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"A" * (12 * 1024 * 1024))

    extract_dir = tmp_path / "out"
    extract_dir.mkdir()
    with zipfile.ZipFile(bomb) as archive:
        with pytest.raises(ValueError, match="compression ratio"):
            _safe_extractall(archive, extract_dir)

    with pytest.raises(ValueError, match="compression ratio"):
        from dms.core.analyzer import _analyze_docx

        _analyze_docx(bomb)
