"""Folder watcher utilities for clean/spoof automation."""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from dms.core import analyzer
from dms.core.sanitizer import remove_all
from dms.core.spoofer import apply_smart_spoof

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
    ):
        super().__init__()
        self.mode = mode
        self.callback = callback
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.include_all = include_all
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

    def process(self, path: str | Path) -> None:
        target = Path(path)
        report = analyzer.analyze(target)
        fields_count = sum(1 for field in report.fields if field.status == "risk")
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.mode == "spoof":
            dest: Path | None = None
            if self.output_dir is not None:
                dest = self.output_dir / f"{target.stem}_spoofed{target.suffix}"
            _, _, _ = apply_smart_spoof(report, output_path=dest)
        else:
            out: Path | None = None
            if self.output_dir is not None:
                out = self.output_dir / f"{target.stem}_cleaned{target.suffix}"
            remove_all(report, out)
        if self.callback:
            self.callback(target, fields_count, True)

    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return
        self._task_queue.put(Path(event.src_path))


def watch_folder(
    folder: Path,
    mode: str = "clean",
    recursive: bool = False,
    callback: WatchCallback | None = None,
    output_dir: Path | None = None,
    include_all: bool = False,
) -> None:
    """Start watching a folder until interrupted."""

    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.daemon = True
    observer.schedule(
        DMSEventHandler(mode=mode, callback=callback, output_dir=output_dir, include_all=include_all),
        str(folder_path),
        recursive=recursive,
    )
    observer.start()
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
