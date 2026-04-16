"""Validation of exiftool tag names used in subprocess argv (defense-in-depth)."""

from __future__ import annotations

import re

_EXIF_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_:.-]+$")


def validate_exif_tag(tag: str) -> str:
    """
    Return *tag* if it contains only [A-Za-z0-9_:.-].

    Exiftool tag names from file metadata are passed as -TAG=...; restricting
    characters avoids unexpected argument splitting or tool-specific quirks.
    """

    if not tag or not _EXIF_TAG_PATTERN.fullmatch(tag):
        raise ValueError(f"Invalid exiftool tag name: {tag!r}")
    return tag
