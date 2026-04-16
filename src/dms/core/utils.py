"""Shared utility helpers for core and interfaces."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path


def get_subprocess_flags() -> int:
    """Return creation flags that hide console windows on Windows."""

    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def remove_exiftool_signature(file_path: Path, exiftool_path: str) -> None:
    """Clear XMPToolkit after edits so files are not fingerprinted as exiftool-processed."""

    # Second pass: check=False if no XMP; -m for minor warnings; never raise over this.
    try:
        subprocess.run(
            [
                exiftool_path,
                "-m",
                "-XMPToolkit=",
                "-XMP-x:toolkit=",
                "-overwrite_original",
                str(file_path),
            ],
            capture_output=True,
            check=False,
            creationflags=get_subprocess_flags(),
        )
    except Exception as exc:  # pragma: no cover - filesystem edge cases
        logging.debug("remove_exiftool_signature failed for %s: %s", file_path, exc)
