"""Shared utility helpers for core and interfaces."""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

EXIFTOOL_TIMEOUT = 120

# ExifTool writes UTF-8. text=True alone decodes with the OS locale (e.g. cp1251
# on Windows), which crashes the reader thread on bytes such as 0x98 (☀).
EXIFTOOL_TEXT_KWARGS = {"text": True, "encoding": "utf-8", "errors": "replace"}


def get_subprocess_flags() -> int:
    """Return creation flags that hide console windows on Windows."""

    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _sanitize_argfile_option(option: str) -> str:
    """Strip line breaks and NUL bytes so values cannot inject extra argfile flags."""

    return option.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\x00", "")


def run_exiftool_with_argfile(
    exiftool_path: str,
    destination: Path,
    options: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run exiftool with options from a UTF-8 argfile.

    Windows exiftool.exe passes argv through an ANSI layer, which corrupts
    non-ASCII values. A UTF-8 argfile preserves them for EXIF and XMP writes.
    """

    sanitized = [
        cleaned
        for item in options
        if (cleaned := _sanitize_argfile_option(item)) and cleaned.startswith("-")
    ]
    payload = ("\n".join(sanitized) + "\n").encode("utf-8")
    fd, argfile_name = tempfile.mkstemp(prefix=".dms_args_", suffix=".txt")
    argfile = Path(argfile_name)
    try:
        with open(fd, "wb") as handle:
            handle.write(payload)
        return subprocess.run(
            [exiftool_path, "-@", str(argfile), "-overwrite_original", str(destination)],
            capture_output=True,
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
            **EXIFTOOL_TEXT_KWARGS,
        )
    finally:
        argfile.unlink(missing_ok=True)


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
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
        )
    except Exception as exc:  # pragma: no cover - filesystem edge cases
        logging.debug("remove_exiftool_signature failed for %s: %s", file_path, exc)
