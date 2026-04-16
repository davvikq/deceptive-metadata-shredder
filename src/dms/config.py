"""Application configuration helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from dms.core.utils import get_subprocess_flags

APP_NAME = "Deceptive Metadata Shredder"
PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_ROOT / "data"
PROJECT_ROOT = PACKAGE_ROOT.parent.parent


def _is_working_exiftool(path: Path) -> bool:
    try:
        result = subprocess.run(
            [str(path), "-ver"],
            check=True,
            capture_output=True,
            text=True,
            creationflags=get_subprocess_flags(),
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return bool(result.stdout.strip())


@lru_cache(maxsize=1)
def get_exiftool_path() -> str | None:
    """Return the preferred exiftool executable path if available."""

    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "bin" / "exiftool.exe")
        search_root = PACKAGE_ROOT / "core" / "analyzer.py"
        for levels in range(1, 6):
            candidate = search_root
            for _ in range(levels):
                candidate = candidate.parent
            candidates.append(candidate / "bin" / "exiftool.exe")
        candidates.append(PACKAGE_ROOT.parent.parent.parent / "exiftool.exe")

    for candidate in candidates:
        if candidate.exists() and _is_working_exiftool(candidate):
            return str(candidate)

    system_path = shutil.which("exiftool")
    if system_path and _is_working_exiftool(Path(system_path)):
        return system_path
    return None


def require_exiftool() -> str:
    """Return exiftool path or raise a helpful error."""

    exiftool = get_exiftool_path()
    if not exiftool:
        raise RuntimeError(
            "exiftool is required for this operation. Install it or place "
            "'exiftool.exe' in the bin/ folder (with bin/exiftool_files)."
        )
    return exiftool


@lru_cache(maxsize=1)
def get_exiftool_version() -> str | None:
    """Return the installed exiftool version string, if available."""

    exiftool = get_exiftool_path()
    if not exiftool:
        return None
    try:
        result = subprocess.run(
            [exiftool, "-ver"],
            check=True,
            capture_output=True,
            text=True,
            creationflags=get_subprocess_flags(),
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip() or None
