"""Tests for exiftool tag validation."""

import pytest

from dms.core.exiftool_tags import validate_exif_tag


def test_validate_accepts_typical_tags() -> None:
    assert validate_exif_tag("Make") == "Make"
    assert validate_exif_tag("XMP:Make") == "XMP:Make"
    assert validate_exif_tag("EXIF:DateTimeOriginal") == "EXIF:DateTimeOriginal"
    assert validate_exif_tag("Composite:GPSLatitude") == "Composite:GPSLatitude"


def test_validate_rejects_empty() -> None:
    with pytest.raises(ValueError, match="Invalid exiftool tag"):
        validate_exif_tag("")


def test_validate_rejects_space_and_semicolon() -> None:
    with pytest.raises(ValueError):
        validate_exif_tag("bad tag")
    with pytest.raises(ValueError):
        validate_exif_tag("foo;rm")


def test_validate_rejects_newline() -> None:
    with pytest.raises(ValueError):
        validate_exif_tag("foo\n-bar")
