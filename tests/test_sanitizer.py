from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import pytest
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
    assert "instrText" in local_names
    assert "DO_NOT_TOUCH" in transformed
