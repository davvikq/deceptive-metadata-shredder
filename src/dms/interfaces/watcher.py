"""Folder watcher utilities for clean/spoof automation."""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler

from dms.config import require_exiftool
from dms.core import analyzer
from dms.core.exiftool_tags import validate_exif_tag
from dms.core.models import FileReport, parse_metadata_datetime
from dms.core.sanitizer import remove_all
from dms.core.spoofer import apply_smart_spoof, set_filesystem_dates
from dms.core.utils import EXIFTOOL_TEXT_KWARGS, EXIFTOOL_TIMEOUT, get_subprocess_flags, remove_exiftool_signature

WatchCallback = Callable[[Path, int, bool], None]


class DMSEventHandler(FileSystemEventHandler):
    """Process newly created files while ignoring DMS-generated outputs."""

    IGNORE_SUFFIXES = ("_cleaned", "_spoofed", "_dms")

    def __init__(
        self,
        mode: str = "clean",
        callback: WatchCallback | None = None,
        output_dir: Path | None = None,
        include_all: bool = False,
        strip_annotations: bool = False,
        strip_attachments: bool = False,
    ):
        super().__init__()
        if mode not in {"clean", "spoof", "spoof_clean"}:
            raise ValueError(f"Unsupported mode: {mode}. Use 'clean', 'spoof', or 'spoof_clean'.")
        self.mode = mode
        self.callback = callback
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.include_all = include_all
        self.strip_annotations = strip_annotations
        self.strip_attachments = strip_attachments
        self._task_queue: queue.Queue[Path] = queue.Queue()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="dms-watch-queue",
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while True:
            target = self._task_queue.get()
            try:
                time.sleep(0.5)
                if not self._wait_until_stable(target):
                    if self.callback:
                        self.callback(target, 0, False)
                else:
                    try:
                        self.process(target)
                    except Exception:
                        logging.exception("Watch folder processing failed: %s", target)
                        if self.callback:
                            self.callback(target, 0, False)
            finally:
                self._task_queue.task_done()

    def should_ignore(self, path: str | Path) -> bool:
        target = Path(path)
        if target.name.startswith("."):
            return True
        if self.output_dir is not None:
            try:
                if target.resolve().is_relative_to(self.output_dir.resolve()):
                    return True
            except (OSError, ValueError, RuntimeError):
                pass
        if self.include_all and self.output_dir is not None:
            return False
        stem = target.stem.lower()
        if any(stem.endswith(suffix) for suffix in self.IGNORE_SUFFIXES):
            return True
        return False

    def _wait_until_stable(self, path: Path, attempts: int = 10, delay: float = 0.2) -> bool:
        previous_size = -1
        for _ in range(attempts):
            try:
                current_size = path.stat().st_size
            except FileNotFoundError:
                return False
            if current_size == previous_size:
                return True
            previous_size = current_size
            time.sleep(delay)
        return path.exists()

    def _strip_residual_after_spoof(self, before: FileReport, dest: Path) -> None:
        reloaded = analyzer.analyze(dest)
        before_values: dict[str, set[str]] = {}
        for field in before.fields:
            if field.is_computed or not field.is_sensitive or field.key in analyzer.FILESYSTEM_DATE_KEYS:
                continue
            tag_id = (field.exiftool_tag or field.key).lower()
            before_values.setdefault(tag_id, set()).add(str(field.value))

        changed_tags: set[str] = set()
        for field in reloaded.fields:
            if field.is_computed or not field.is_sensitive or field.key in analyzer.FILESYSTEM_DATE_KEYS:
                continue
            tag_id = (field.exiftool_tag or field.key).lower()
            prev = before_values.get(tag_id)
            if prev is None or str(field.value) not in prev:
                changed_tags.add(tag_id)

        residual = [
            field
            for field in reloaded.fields
            if field.is_sensitive
            and not field.is_computed
            and field.key not in analyzer.FILESYSTEM_DATE_KEYS
            and (field.exiftool_tag or field.key).lower() not in changed_tags
        ]
        if not residual:
            return

        exiftool = require_exiftool()
        args = [exiftool, "-m"]
        applied = 0
        for field in residual:
            try:
                safe = validate_exif_tag(field.exiftool_tag)
            except ValueError:
                logging.warning("Skipping residual field: file=%s key=%s tag=%r", dest, field.key, field.exiftool_tag)
                continue
            args.append(f"-{safe}=")
            applied += 1
        if applied == 0:
            return
        args.extend(["-overwrite_original", str(dest)])
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
            **EXIFTOOL_TEXT_KWARGS,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to remove residual fields.")
        remove_exiftool_signature(dest, exiftool)
        anchor_date: datetime | None = next(
            (
                parsed
                for field in reloaded.fields
                if field.category == "dates"
                and field.key not in analyzer.FILESYSTEM_DATE_KEYS
                and (parsed := parse_metadata_datetime(field.value)) is not None
            ),
            None,
        )
        if anchor_date is not None:
            set_filesystem_dates(dest, anchor_date)

    def process(self, path: str | Path) -> None:
        target = Path(path)
        report = analyzer.analyze(target)
        fields_count = sum(1 for field in report.fields if field.status == "risk")
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.mode in {"spoof", "spoof_clean"}:
            if self.output_dir is not None:
                dest = self.output_dir / f"{target.stem}_spoofed{target.suffix}"
            else:
                dest = target.with_name(f"{target.stem}_spoofed{target.suffix}")
            apply_smart_spoof(report, output_path=dest)
            if self.mode == "spoof_clean":
                self._strip_residual_after_spoof(report, dest)
        else:
            out: Path | None = None
            if self.output_dir is not None:
                out = self.output_dir / f"{target.stem}_cleaned{target.suffix}"
            remove_all(
                report,
                out,
                strip_annotations=self.strip_annotations,
                strip_attachments=self.strip_attachments,
            )
        if self.callback:
            self.callback(target, fields_count, True)

    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return
        self._task_queue.put(Path(event.src_path))
