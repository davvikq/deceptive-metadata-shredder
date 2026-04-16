"""Domain models for metadata reports and spoofing profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MetaField:
    exiftool_tag: str
    key: str
    label: str
    value: Any
    category: str
    spoofable: bool
    is_sensitive: bool
    is_computed: bool = False
    status: str = "risk"
    spoof_value: Any = None


@dataclass(slots=True)
class FileReport:
    path: Path
    file_type: str
    fields: list[MetaField]
    thumbnail: bytes | None = None
    warnings: list[str] = field(default_factory=list)
    empty_reason: str | None = None
    exiftool_version: str | None = None

    def by_key(self) -> dict[str, MetaField]:
        """Fields keyed by full key and by short name (suffix after : or .)."""

        indexed: dict[str, MetaField] = {}
        for field in self.fields:
            indexed[field.key] = field
            normalized = field.key.split(".")[-1].split(":")[-1]
            indexed.setdefault(normalized, field)
        return indexed


@dataclass(slots=True)
class SpoofProfile:
    gps_mode: str = "smart"
    gps_target: tuple[float, float] | None = None
    device_make: str | None = None
    device_model: str | None = None
    author: str | None = None
    dates_mode: str = "keep"
    dates_shift_days: int = 0


@dataclass(slots=True)
class Device:
    id: str
    make: str
    model: str
    software: str | None
    year: int
    exif_overrides: dict[str, Any] = field(default_factory=dict)


def parse_metadata_datetime(value: Any) -> datetime | None:
    """Parse common EXIF and document datetime values."""

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    formats = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "D:%Y%m%d%H%M%S",
        "D:%Y%m%d%H%M%S%z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
