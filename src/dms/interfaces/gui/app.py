"""PySide6 desktop application entry point."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import copy
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QKeyEvent, QMouseEvent, QPainter, QPalette, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dms.core import analyzer
from dms.core.error_messages import classify_exiftool_error, get_error
from datetime import datetime
from dms.core.models import FileReport, MetaField, parse_metadata_datetime
from dms.core.constants import ALWAYS_DELETE_PREFIXES, ALWAYS_DELETE_TAGS, REGION_XMP_NUKE_ARGS
from dms.core.exiftool_tags import validate_exif_tag
from dms.core.sanitizer import remove_all, remove_field
from dms.core.utils import get_subprocess_flags, remove_exiftool_signature
from dms.config import require_exiftool
from dms.core.spoofer import apply_field_spoof, apply_smart_spoof, set_filesystem_dates, spoof_filesystem_dates
from dms.interfaces.gui.screens.screen_batch import ScreenBatch
from dms.interfaces.gui.screens.screen_compare import ScreenCompare
from dms.interfaces.gui.screens.screen_drop import ScreenDrop
from dms.interfaces.gui.screens.screen_report import ScreenReport
from dms.interfaces.gui.theme import COLORS, GLOBAL_QSS, tr
from dms.interfaces.gui.widgets.glass_card import GlassCard
from dms.interfaces.gui.widgets.toast import Toast

# Max time to wait for QThread workers to finish after requestInterruption() on window close.
_CLOSE_JOIN_TIMEOUT_MS = 30_000

# Adaptive min/start size vs QGuiApplication.primaryScreen().availableGeometry() so the
# Windows title bar is not clipped on e.g. 1366x768 with taskbar (see _center_on_screen).
_PREFERRED_MIN_W = 1100
_PREFERRED_MIN_H = 680
_TITLEBAR_WORK_AREA_MARGIN = 40
_ABSOLUTE_MIN_W = 320
_ABSOLUTE_MIN_H = 240

_DMS_PROCESSED_PATTERNS = [
    re.compile(r"_cleaned$"),
    re.compile(r"_cleaned_cleaned"),
    re.compile(r"_spoofed$"),
    re.compile(r"_dms$"),
]

def _build_file_dialog_filter() -> str:
    """Build a Qt file-dialog filter string from the supported formats table."""
    all_exts = " ".join(f"*{ext}" for ext in sorted(analyzer.SUPPORTED_FORMATS))
    images = " ".join(
        f"*{ext}" for ext, kind in sorted(analyzer.SUPPORTED_FORMATS.items())
        if kind in {"jpeg", "png", "heic", "heif", "tiff", "webp"}
    )
    raw = " ".join(
        f"*{ext}" for ext, kind in sorted(analyzer.SUPPORTED_FORMATS.items())
        if kind == "raw"
    )
    docs = "*.pdf *.docx"
    video = "*.mp4 *.mov"
    return (
        f"All Supported ({all_exts});;"
        f"Images ({images});;"
        f"RAW ({raw});;"
        f"Documents ({docs});;"
        f"Video ({video});;"
        "All Files (*)"
    )

_FILE_DIALOG_FILTER = _build_file_dialog_filter()


def looks_like_dms_output(path: Path) -> bool:
    """True if stem looks like *_cleaned / *_spoofed / *_dms output."""

    stem = path.stem.lower()
    return any(pattern.search(stem) for pattern in _DMS_PROCESSED_PATTERNS)


class DMSOutputWarningDialog(QDialog):
    """Warn when opened paths look like prior DMS exports."""

    SKIP = "skip"
    ADD = "add"
    CANCEL = "cancel"

    def __init__(self, suspicious: list[Path], locale: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr(locale, "dms_output_title"))
        self.setMinimumWidth(420)
        self.result_action = self.CANCEL

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        icon_label = QLabel("\u26a0", self)
        icon_label.setFont(QFont("Segoe UI Emoji", 28))
        icon_label.setStyleSheet(f"color:{COLORS['warning']};")
        layout.addWidget(icon_label, alignment=Qt.AlignCenter)

        title = QLabel(tr(locale, "dms_output_title"), self)
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        body = QLabel(tr(locale, "dms_output_body"), self)
        body.setFont(QFont("Segoe UI", 11))
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{COLORS['text_secondary']};")
        layout.addWidget(body)

        file_list = "\n".join(f"\u2022 {p.name}" for p in suspicious[:10])
        if len(suspicious) > 10:
            file_list += f"\n\u2022 \u2026 and {len(suspicious) - 10} more"
        files_label = QLabel(file_list, self)
        files_label.setFont(QFont("Cascadia Code", 10))
        files_label.setStyleSheet("color:#a5f3fc; padding: 8px 0;")
        files_label.setWordWrap(True)
        layout.addWidget(files_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_skip = QPushButton(tr(locale, "dms_output_skip"), self)
        btn_skip.setFont(QFont("Segoe UI", 11, QFont.Medium))
        btn_skip.setStyleSheet(
            f"QPushButton {{ background: rgba(245,158,11,0.18); border: 1px solid {COLORS['warning']};"
            "border-radius: 10px; padding: 8px 18px; color: #f8fafc; }"
            f"QPushButton:hover {{ background: rgba(245,158,11,0.3); color: #f8fafc; }}"
        )
        btn_skip.clicked.connect(lambda: self._finish(self.SKIP))
        btn_row.addWidget(btn_skip)

        btn_add = QPushButton(tr(locale, "dms_output_add"), self)
        btn_add.setFont(QFont("Segoe UI", 11, QFont.Medium))
        btn_add.setStyleSheet(
            f"QPushButton {{ background: {COLORS['accent']}; border: 1px solid {COLORS['accent']};"
            "border-radius: 10px; padding: 8px 18px; color: #f8fafc; }"
            f"QPushButton:hover {{ background: {COLORS['accent_hover']}; color: #f8fafc; }}"
        )
        btn_add.clicked.connect(lambda: self._finish(self.ADD))
        btn_row.addWidget(btn_add)

        btn_cancel = QPushButton(tr(locale, "dms_output_cancel"), self)
        btn_cancel.setFont(QFont("Segoe UI", 11, QFont.Medium))
        btn_cancel.setStyleSheet(
            "QPushButton { background: rgba(239,68,68,0.15); border: 1px solid #ef4444;"
            "border-radius: 10px; padding: 8px 18px; color: #f8fafc; }"
            "QPushButton:hover { background: rgba(239,68,68,0.3); color: #f8fafc; }"
        )
        btn_cancel.clicked.connect(lambda: self._finish(self.CANCEL))
        btn_row.addWidget(btn_cancel)

        layout.addLayout(btn_row)

    def _finish(self, action: str) -> None:
        self.result_action = action
        self.accept()


@dataclass(slots=True)
class FileSession:
    """Original path, temp work copy, and before/after reports."""

    original_path: Path
    work_path: Path
    original_report: FileReport
    current_report: FileReport
    spoofed_keys: set[str] = field(default_factory=set)
    removed_keys: set[str] = field(default_factory=set)
    temp_dir: Path | None = None
    is_modified: bool = False
    spoofed_dates_anchor: datetime | None = None


LINKED_TAGS = {
    "datetimeoriginal": ["datetimeoriginal", "subsectimeoriginal", "capturedat"],
    "createdate": ["datecreated", "creationdate", "capturedat", "xmpdatecreated"],
    "modifydate": ["modifiedat", "pdfmodified", "metadatadate"],
    "gpsdatetime": ["gpsdatestamp", "gpstimestamp", "gpsdatetime"],
    "gpslatitude": ["gpsposition", "gpslatituderef", "gpslongituderef", "gpslongitude", "gpsaltitude", "gpsaltituderef"],
    "make": ["devicemake", "devicemodel", "lensmodel", "lensid", "lensmake", "creatortool", "software", "model"],
    "author": ["creator", "artist", "xmpcreator", "dccreator"],
    # exiftool updates FileModify/Access/Create together — link keys for UI state.
    "filemodifydate": ["fileaccessdate", "filecreatedate"],
    "datecreated": ["createdate", "creationdate", "capturedat", "xmpdatecreated"],
}

_SYSTEM_DATE_KEYS: frozenset[str] = frozenset({"FileModifyDate", "FileAccessDate", "FileCreateDate"})


def _canonical_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _field_aliases(field: MetaField) -> set[str]:
    aliases = {
        _canonical_key(field.key),
        _canonical_key(field.label),
        _canonical_key(field.exiftool_tag),
        _canonical_key(field.exiftool_tag.split(":")[-1]),
        _canonical_key(field.exiftool_tag.split(".")[-1]),
    }
    return {item for item in aliases if item}


def _expand_linked_keys(key: str) -> set[str]:
    canonical = _canonical_key(key)
    expanded = {canonical}
    for source, linked in LINKED_TAGS.items():
        linked_set = {_canonical_key(item) for item in linked}
        if canonical == source or canonical in linked_set:
            expanded.add(source)
            expanded.update(linked_set)
    return expanded


def _record_change(session: FileSession, key: str, state: str) -> None:
    target = session.spoofed_keys if state == "spoofed" else session.removed_keys
    other = session.removed_keys if state == "spoofed" else session.spoofed_keys
    for expanded in _expand_linked_keys(key):
        target.add(expanded)
        other.discard(expanded)


def _populate_session_keys(session: FileSession) -> None:
    original_by_key = {f.key: str(f.value) for f in session.original_report.fields}
    current_by_key = {f.key: str(f.value) for f in session.current_report.fields}
    session.spoofed_keys.clear()
    session.removed_keys.clear()
    for key, orig_val in original_by_key.items():
        cur_val = current_by_key.get(key)
        if cur_val is None:
            _record_change(session, key, "removed")
        elif orig_val != cur_val:
            _record_change(session, key, "spoofed")


def _apply_states_to_report(session: FileSession) -> None:
    for field in session.current_report.fields:
        aliases = _field_aliases(field)
        if aliases & session.removed_keys:
            field.status = "removed"
        elif aliases & session.spoofed_keys:
            field.status = "spoofed"
        else:
            field.status = "risk" if field.is_sensitive else "clean"


def _is_exiftool_warnings_only(stderr: str) -> bool:
    if not stderr:
        return True
    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Warning:"):
            continue
        if stripped.startswith("Error: [minor]"):
            continue
        if stripped == "Nothing to do.":
            continue
        return False
    return True


def _is_always_delete_field(meta_field: MetaField) -> bool:
    normalized = meta_field.key.split(":")[-1].split(".")[-1]
    if normalized in ALWAYS_DELETE_TAGS:
        return True
    for prefix in ALWAYS_DELETE_PREFIXES:
        if normalized.startswith(prefix):
            return True
    return False


def _is_region_field(meta_field: MetaField) -> bool:
    normalized = meta_field.key.split(":")[-1].split(".")[-1]
    for prefix in ALWAYS_DELETE_PREFIXES:
        if normalized.startswith(prefix):
            return True
    return False


def _nuke_region_blocks(target: Path) -> None:
    exiftool = require_exiftool()
    args = [exiftool, "-overwrite_original", "-m"]
    args.extend(REGION_XMP_NUKE_ARGS)
    args.append(str(target))
    subprocess.run(
        args, capture_output=True, text=True,
        creationflags=get_subprocess_flags(),
    )


def get_log_path() -> Path:
    """Return a writable log path for GUI errors."""

    if getattr(sys, "frozen", False):
        app_data = Path(os.environ.get("APPDATA", Path.home()))
        log_dir = app_data / "DeceptiveMetadataShredder"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "dms_errors.log"
    return Path(__file__).parent.parent.parent / "dms_errors.log"


def configure_logging() -> None:
    """Append ERROR logs to a writable path (AppData when frozen)."""

    logging.basicConfig(
        filename=str(get_log_path()),
        level=logging.ERROR,
        format="%(asctime)s — %(levelname)s — %(message)s",
        force=True,
    )


def _exiftool_banner_key() -> str:
    if sys.platform.startswith("win"):
        return "warning_exiftool_windows" if getattr(sys, "frozen", False) else "warning_exiftool_missing"
    if sys.platform == "darwin":
        return "warning_exiftool_macos"
    return "warning_exiftool_linux"


class LanguageChip(QLabel):
    clicked = Signal(str)

    def __init__(self, language: str, parent: QWidget | None = None):
        super().__init__(language.upper(), parent)
        self.language = language
        self.setObjectName("lang_btn")
        self.setFixedWidth(36)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self._set_active(False)

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_active(self, active: bool) -> None:
        self._set_active(active)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # pragma: no cover - GUI interaction
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.language)
        super().mousePressEvent(event)


class WorkerThread(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, task, lang: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.task = task
        self.lang = lang

    def run(self) -> None:  # pragma: no cover - thread bridge
        if self.isInterruptionRequested():
            return
        try:
            self.result.emit(self.task())
        except FileNotFoundError:
            self.error.emit(get_error("file_not_found", self.lang))
        except PermissionError:
            self.error.emit(get_error("file_permission", self.lang))
        except TypeError:
            self.error.emit(get_error("missing_argument", self.lang))
        except RuntimeError as exc:
            message = str(exc)
            lowered = message.lower()
            if "exiftool" in lowered and ("required" in lowered or "not found" in lowered):
                self.error.emit(get_error("exiftool_not_found", self.lang))
            else:
                self.error.emit(classify_exiftool_error(message, self.lang))
        except Exception as exc:  # pragma: no cover - defensive bridge
            logging.error("Unexpected worker error: %s", exc, exc_info=True)
            self.error.emit(get_error("unexpected_error", self.lang))


class SmartSpoofWorker(QThread):
    result = Signal(object, list, list)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, report: FileReport, lang: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.report = report
        self.lang = lang

    def run(self) -> None:  # pragma: no cover - thread bridge
        if self.isInterruptionRequested():
            return
        try:
            logging.debug("Smart spoof worker: start path=%s", self.report.path)

            def emit_progress(message: str) -> None:
                progress_map = {
                    "Spoofing GPS...": tr(self.lang, "progress_gps"),
                    "Spoofing device...": tr(self.lang, "progress_device"),
                    "Spoofing dates...": tr(self.lang, "progress_dates"),
                    "Spoofing author...": tr(self.lang, "progress_author"),
                }
                message = progress_map.get(message, message)
                logging.debug("Smart spoof progress: %s", message)
                self.progress.emit(message)

            destination, changes, info_codes = apply_smart_spoof(self.report, progress_callback=emit_progress)
            new_report = analyzer.analyze(destination)
            logging.debug("Smart spoof worker: done path=%s", destination)
            self.result.emit(new_report, changes, info_codes)
        except FileNotFoundError:
            logging.error("Smart spoof worker: file not found", exc_info=True)
            self.error.emit(get_error("file_not_found", self.lang))
        except PermissionError:
            logging.error("Smart spoof worker: permission error", exc_info=True)
            self.error.emit(get_error("file_permission", self.lang))
        except TypeError:
            logging.error("Smart spoof worker: missing argument", exc_info=True)
            self.error.emit(get_error("missing_argument", self.lang))
        except RuntimeError as exc:
            message = str(exc)
            logging.error("Smart spoof worker runtime error: %s", message, exc_info=True)
            lowered = message.lower()
            if "exiftool" in lowered and ("required" in lowered or "not found" in lowered):
                self.error.emit(get_error("exiftool_not_found", self.lang))
            else:
                self.error.emit(classify_exiftool_error(message, self.lang))
        except Exception as exc:  # pragma: no cover - defensive bridge
            logging.error("Smart spoof error: %s", exc, exc_info=True)
            self.error.emit(get_error("unexpected_error", self.lang))


class BatchWorker(QThread):
    file_started = Signal(int)
    file_analyzed = Signal(int, int)
    file_risk_updated = Signal(int, int)
    file_progress = Signal(int, int)
    file_done = Signal(int, bool)
    file_session_ready = Signal(int)
    all_done = Signal(int, int)
    error = Signal(str)

    def __init__(self, sessions: list[FileSession], mode: str, lang: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.sessions = sessions
        self.mode = mode
        self.lang = lang

    def _clean_residual(self, report: FileReport, session: FileSession | None = None) -> int:
        spoofed = session.spoofed_keys if session is not None else set()

        spoofed_categories: set[str] = set()
        for field in report.fields:
            aliases = _field_aliases(field)
            if field.status == "spoofed" or aliases & spoofed:
                spoofed_categories.add(field.category)

        residual_fields: list[MetaField] = []
        for field in report.fields:
            if not field.is_sensitive or field.is_computed:
                continue
            if field.status in {"spoofed", "removed", "clean"}:
                continue
            if _is_always_delete_field(field):
                continue
            if field.key in _SYSTEM_DATE_KEYS:
                continue
            aliases = _field_aliases(field)
            if aliases & spoofed:
                continue
            if field.category != "other" and field.category in spoofed_categories:
                continue
            residual_fields.append(field)

        logging.debug(
            "batch _clean_residual: spoofed_keys=%s, spoofed_categories=%s, residual=%s",
            spoofed, spoofed_categories, [f.key for f in residual_fields],
        )

        always_delete = [
            field for field in report.fields
            if _is_always_delete_field(field)
        ]

        has_region = any(_is_region_field(f) for f in always_delete)
        if has_region:
            _nuke_region_blocks(report.path)

        non_region_ad = [f for f in always_delete if not _is_region_field(f)]
        all_standard = residual_fields + [
            f for f in non_region_ad
            if f.exiftool_tag not in {r.exiftool_tag for r in residual_fields}
        ]
        total = len(residual_fields) + len(always_delete)
        if all_standard:
            exiftool = require_exiftool()
            args = [exiftool, "-m"]
            for field in all_standard:
                try:
                    safe = validate_exif_tag(field.exiftool_tag)
                except ValueError:
                    logging.warning(
                        "Skipping residual field: file=%s key=%s tag=%r",
                        report.path,
                        field.key,
                        field.exiftool_tag,
                    )
                    continue
                args.append(f"-{safe}=")
            if len(args) > 2:
                args.extend(["-overwrite_original", str(report.path)])
                result = subprocess.run(args, capture_output=True, text=True, creationflags=get_subprocess_flags())
                stderr = (result.stderr or "").strip()
                if result.returncode != 0 and not _is_exiftool_warnings_only(stderr):
                    raise RuntimeError(stderr or "Failed to clean residual fields.")
        return total

    def run(self) -> None:  # pragma: no cover - thread bridge
        # Long-running steps (analyze, exiftool) cannot be aborted mid-call without core support;
        # isInterruptionRequested() is checked between steps and between files (cooperative cancel).
        success_count = 0
        fail_count = 0
        for index, session in enumerate(self.sessions):
            if self.isInterruptionRequested():
                logging.info("Batch processing interrupted before starting file index %s", index)
                break
            self.file_started.emit(index)
            self.file_progress.emit(index, 0)
            try:
                report = analyzer.analyze(session.work_path)
                if self.isInterruptionRequested():
                    logging.info("Batch processing interrupted after analyze index %s", index)
                    self.file_done.emit(index, False)
                    fail_count += 1
                    break
                session.original_report = copy.deepcopy(report)
                self.file_analyzed.emit(index, sum(1 for field in report.fields if field.is_sensitive))
                self.file_progress.emit(index, 40)

                if self.mode == "remove":
                    remove_all(report, output_path=session.work_path)
                else:
                    destination, changes, _info_codes = apply_smart_spoof(report)
                    if destination != session.work_path and destination.exists():
                        shutil.copy2(destination, session.work_path)
                    if self.mode == "spoof_clean":
                        refreshed = analyzer.analyze(session.work_path)
                        session.current_report = refreshed
                        _populate_session_keys(session)
                        _apply_states_to_report(session)
                        self._clean_residual(session.current_report, session=session)

                if self.isInterruptionRequested():
                    logging.info("Batch processing interrupted after processing index %s", index)
                    self.file_done.emit(index, False)
                    fail_count += 1
                    break

                self.file_progress.emit(index, 90)
                session.current_report = analyzer.analyze(session.work_path)

                original_by_key = {f.key: str(f.value) for f in session.original_report.fields}
                changed_keys: set[str] = set()
                current_keys: set[str] = set()
                for field in session.current_report.fields:
                    current_keys.add(field.key)
                    orig_val = original_by_key.get(field.key)
                    if orig_val is None or orig_val != str(field.value):
                        changed_keys.add(field.key)
                removed_keys = set(original_by_key) - current_keys

                remaining_risk = sum(
                    1
                    for field in session.current_report.fields
                    if field.is_sensitive
                    and not field.is_computed
                    and field.key not in changed_keys
                    and field.key not in removed_keys
                    and field.key not in _SYSTEM_DATE_KEYS
                )
                self.file_risk_updated.emit(index, remaining_risk)
                self.file_progress.emit(index, 100)
                session.is_modified = True

                _populate_session_keys(session)
                _apply_states_to_report(session)
                self.file_session_ready.emit(index)
                self.file_done.emit(index, True)
                success_count += 1
            except Exception as exc:
                logging.error(
                    "Batch failed for %s: %s: %s",
                    session.original_path.name, type(exc).__name__, exc,
                    exc_info=True,
                )
                self.file_done.emit(index, False)
                fail_count += 1
        self.all_done.emit(success_count, fail_count)


class MainWindow(QMainWindow):
    """Main window: drop zone, report/editor, batch queue, compare."""

    def __init__(self):
        super().__init__()
        self.locale = "en"
        self.session: FileSession | None = None
        self.batch_sessions: list[FileSession] = []
        self.current_report: FileReport | None = None
        self.field_states: dict[str, str] = {}
        self.selected_field_key: str | None = None
        self._workers: set[QThread] = set()
        # Single session-scoped worker (analyze/spoof/remove); excludes BatchWorker (separate lifecycle).
        self._active_session_worker: QThread | None = None
        self._active_toasts: list[Toast] = []
        self._batch_worker: BatchWorker | None = None

        # Standard window chrome + resize on all Windows builds (portable exe edge cases).
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.setWindowTitle(tr(self.locale, "app_title"))
        self.setWindowIcon(_get_app_icon())
        self.setAcceptDrops(True)
        # Min size + initial resize/move from availableGeometry() (not fixed 1100x680 vs short work area).
        self._center_on_screen()

        central = QWidget(self)
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.topbar = GlassCard(central)
        self.topbar.setFixedHeight(52)
        top_layout = QHBoxLayout(self.topbar)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(8)

        self.back_button = QPushButton(self.topbar)
        self.back_button.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.back_button.clicked.connect(self.navigate_back)
        self.back_button.hide()
        top_layout.addWidget(self.back_button)

        self.compare_button = QPushButton(self.topbar)
        self.compare_button.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.compare_button.setStyleSheet(
            "QPushButton { background: transparent; border-color: rgba(255,255,255,0.12); color: #f8fafc; }"
        )
        self.compare_button.clicked.connect(self.show_compare)
        self.compare_button.hide()
        top_layout.addWidget(self.compare_button)

        top_layout.addStretch(1)
        self.title_label = QLabel(self.topbar)
        self.title_label.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.title_label.setStyleSheet("color:#94a3b8;")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)

        self.lang_buttons: dict[str, LanguageChip] = {}
        for language in ("en", "ru", "zh"):
            button = LanguageChip(language, self.topbar)
            button.clicked.connect(self.set_locale)
            self.lang_buttons[language] = button
            top_layout.addWidget(button)

        root.addWidget(self.topbar)

        self.banner = QLabel(central)
        self.banner.setVisible(False)
        self.banner.setWordWrap(True)
        self.banner.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.banner.setStyleSheet(
            "background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.4);"
            "border-radius: 10px; color: #fde68a; padding: 10px 14px;"
        )
        root.addWidget(self.banner)

        self.stack = QStackedWidget(central)
        root.addWidget(self.stack, 1)

        self.drop_screen = ScreenDrop(self.get_current_locale, self)
        self.drop_screen.browseRequested.connect(self.browse_file)
        self.report_screen = ScreenReport(self.get_current_locale, self)
        self.report_screen.removeAllRequested.connect(self.remove_all_metadata)
        self.report_screen.smartSpoofRequested.connect(self.smart_spoof_all)
        self.report_screen.saveRequested.connect(self.save_copy)
        self.report_screen.cleanResidualRequested.connect(self.clean_residual_fields)
        self.report_screen.fieldActionRequested.connect(self.handle_field_action)
        self.report_screen.editorApplyRequested.connect(self.apply_editor_changes)
        self.report_screen.editorClosed.connect(self.close_editor)
        self.report_screen.editor.validationError.connect(self._show_editor_error)
        self.batch_screen = ScreenBatch(self.get_current_locale, self)
        self.batch_screen.backRequested.connect(self.navigate_back)
        self.batch_screen.addMoreRequested.connect(self.add_more_batch_files)
        self.batch_screen.processRequested.connect(self.process_batch)
        self.batch_screen.saveAllRequested.connect(self.save_all_batch)
        self.batch_screen.removeItemRequested.connect(self.remove_batch_item)
        self.batch_screen.openItemRequested.connect(self.open_batch_item)
        self.compare_screen = ScreenCompare(self.get_current_locale, self)
        self.compare_screen.backRequested.connect(self.show_report_from_compare)
        self.compare_screen.saveRequested.connect(self.save_copy)

        self.stack.addWidget(self.drop_screen)
        self.stack.addWidget(self.report_screen)
        self.stack.addWidget(self.batch_screen)
        self.stack.addWidget(self.compare_screen)

        self.refresh_locale()
        self.check_exiftool()
        self.show_drop_screen()

    def _center_on_screen(self) -> None:
        """Set minimum size and initial position from the primary screen work area (excludes taskbar)."""

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.setMinimumSize(_PREFERRED_MIN_W, _PREFERRED_MIN_H)
            self.resize(_PREFERRED_MIN_W, _PREFERRED_MIN_H)
            return
        avail = screen.availableGeometry()
        w, h = avail.width(), avail.height()
        min_w = max(_ABSOLUTE_MIN_W, min(_PREFERRED_MIN_W, w))
        min_h = max(_ABSOLUTE_MIN_H, min(_PREFERRED_MIN_H, h - _TITLEBAR_WORK_AREA_MARGIN))
        start_w = max(min_w, min(_PREFERRED_MIN_W, int(w * 0.9)))
        start_h = max(min_h, min(_PREFERRED_MIN_H, int(h * 0.9)))
        self.setMinimumSize(min_w, min_h)
        self.resize(start_w, start_h)
        x = avail.x() + (w - start_w) // 2
        y = avail.y() + (h - start_h) // 2
        self.move(x, y)

    def paintEvent(self, event) -> None:  # pragma: no cover - paint only
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS["bg_primary"]))
        indigo = QRadialGradient(200, 150, 300)
        indigo.setColorAt(0.0, QColor(67, 56, 202, 64))
        indigo.setColorAt(1.0, QColor(67, 56, 202, 0))
        painter.fillRect(self.rect(), indigo)
        violet = QRadialGradient(self.width() - 150, self.height() - 100, 220)
        violet.setColorAt(0.0, QColor(124, 58, 237, 51))
        violet.setColorAt(1.0, QColor(124, 58, 237, 0))
        painter.fillRect(self.rect(), violet)
        super().paintEvent(event)

    def resizeEvent(self, event) -> None:  # pragma: no cover - layout only
        super().resizeEvent(event)
        if self._active_toasts:
            self._layout_toasts()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # pragma: no cover - GUI interaction
        if event.key() == Qt.Key_Escape and self.stack.currentWidget() in {
            self.report_screen,
            self.batch_screen,
            self.compare_screen,
        }:
            self.navigate_back()
            event.accept()
            return
        super().keyPressEvent(event)

    def get_current_locale(self) -> str:
        return self.locale

    def _canonical_key(self, value: str) -> str:
        return _canonical_key(value)

    def _field_aliases(self, field: MetaField) -> set[str]:
        return _field_aliases(field)

    def _expand_linked_keys(self, key: str) -> set[str]:
        return _expand_linked_keys(key)

    def _record_session_changes(self, keys: set[str] | None, state: str) -> None:
        if not keys or self.session is None:
            return
        for key in keys:
            _record_change(self.session, key, state)
        logging.debug("spoofed_keys after operation: %s", self.session.spoofed_keys)

    def _apply_session_states(self, report: FileReport) -> dict[str, str]:
        states: dict[str, str] = {}
        if self.session is None:
            for field in report.fields:
                field.status = "risk" if field.is_sensitive else "clean"
                states[field.key] = field.status
            return states

        for field in report.fields:
            aliases = _field_aliases(field)
            if aliases & self.session.removed_keys:
                field.status = "removed"
            elif aliases & self.session.spoofed_keys:
                field.status = "spoofed"
            else:
                field.status = "risk" if field.is_sensitive else "clean"
            states[field.key] = field.status
        return states

    def _residual_fields(self, report: FileReport | None = None) -> list[MetaField]:
        current = report or self.current_report
        if current is None:
            return []
        spoofed = self.session.spoofed_keys if self.session is not None else set()
        spoofed_lower = {k.lower() for k in spoofed}

        # Partial category spoof → don't strip sibling tags user may still want.
        spoofed_categories: set[str] = set()
        for field in current.fields:
            aliases = self._field_aliases(field)
            if aliases & spoofed or field.status == "spoofed":
                spoofed_categories.add(field.category)

        result: list[MetaField] = []
        for field in current.fields:
            if not field.is_sensitive or field.is_computed:
                continue
            if field.status in {"spoofed", "removed", "clean"}:
                continue
            if _is_always_delete_field(field):
                continue
            aliases = self._field_aliases(field)
            if aliases & spoofed:
                continue
            if field.key.lower() in spoofed_lower:
                continue
            linked_hit = False
            for _source, linked in LINKED_TAGS.items():
                linked_set = {self._canonical_key(item) for item in linked}
                field_canonical = self._canonical_key(field.key)
                if field_canonical in linked_set or _source == field_canonical:
                    if linked_set & spoofed or _source in spoofed:
                        linked_hit = True
                        break
            if linked_hit:
                continue
            if field.category != "other" and field.category in spoofed_categories:
                continue
            result.append(field)
        return result

    def _update_clean_residual_visibility(self) -> None:
        if self.session is None:
            self.report_screen.set_clean_residual_visible(False)
            return
        has_residual = bool(self._residual_fields())
        has_always_delete = any(
            _is_always_delete_field(field)
            for field in (self.current_report.fields if self.current_report else [])
        )
        visible = self.session.is_modified and (has_residual or has_always_delete)
        self.report_screen.set_clean_residual_visible(visible)

    def check_exiftool(self) -> None:
        messages: list[str] = []
        try:
            analyzer.find_exiftool()
        except FileNotFoundError:
            messages.append(tr(self.locale, _exiftool_banner_key()))
        if self.current_report is not None and self.current_report.file_type == "raw":
            messages.append(tr(self.locale, "raw_banner"))
        self.banner.setText("\n".join(messages))
        self.banner.setVisible(bool(messages))

    def refresh_locale(self) -> None:
        self.setWindowTitle(tr(self.locale, "app_title"))
        self.back_button.setText(f"< {tr(self.locale, 'back')}")
        self.compare_button.setText(tr(self.locale, "compare_btn"))
        for language, button in self.lang_buttons.items():
            button.setText(language.upper())
            button.set_active(language == self.locale)
        self.drop_screen.refresh_locale()
        self.report_screen.refresh_locale()
        self.batch_screen.refresh_locale()
        self.compare_screen.refresh_locale()
        self.check_exiftool()
        self._update_topbar_context()

    def set_locale(self, locale: str) -> None:
        self.locale = locale
        self.refresh_locale()

    def _save_session_copy_via_dialog(self) -> bool:
        if self.session is None:
            return False
        original_path = self.session.original_path
        default_name = f"{original_path.stem}_cleaned{original_path.suffix}"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            tr(self.locale, "save_dialog_title"),
            str(original_path.parent / default_name),
            f"Files (*{original_path.suffix})",
        )
        if not save_path:
            return False
        shutil.copy2(self.session.work_path, save_path)
        self.session.is_modified = False
        self._update_topbar_context()
        self.show_toast(tr(self.locale, "saved_toast", filename=Path(save_path).name), "success")
        return True

    def _confirm_unsaved_changes(self) -> str:
        if self.session is None or not self.session.is_modified:
            return "discard"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(tr(self.locale, "unsaved_title"))
        dialog.setText(tr(self.locale, "unsaved_body"))
        discard = dialog.addButton(tr(self.locale, "unsaved_discard"), QMessageBox.DestructiveRole)
        save_first = dialog.addButton(tr(self.locale, "unsaved_save_first"), QMessageBox.AcceptRole)
        dialog.addButton(tr(self.locale, "unsaved_cancel"), QMessageBox.RejectRole)
        dialog.setDefaultButton(save_first)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is discard:
            return "discard"
        if clicked is save_first:
            return "save"
        return "cancel"

    def _guard_unsaved_changes(self) -> bool:
        choice = self._confirm_unsaved_changes()
        if choice == "cancel":
            return False
        if choice == "save":
            return self._save_session_copy_via_dialog()
        return True

    def show_report_screen(self, report: FileReport) -> None:
        if self.session is not None:
            self.session.current_report = report
        self.current_report = report
        self.field_states = self._apply_session_states(report)
        self.back_button.show()
        selected = None
        if self.selected_field_key:
            selected = next((field for field in report.fields if field.key == self.selected_field_key), None)
        display_path = self.session.original_path if self.session is not None else report.path
        self.report_screen.set_report(report, self.field_states, selected, display_path=display_path)
        self._update_clean_residual_visibility()
        # setCurrentWidget before topbar: Compare button visibility uses currentWidget().
        self.stack.setCurrentWidget(self.report_screen)
        self._update_topbar_context()
        self.check_exiftool()

    def _confirm_raw_operation(self) -> bool:
        if self.current_report is None or self.current_report.file_type != "raw":
            return True
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(tr(self.locale, "raw_warning_title"))
        dialog.setText(tr(self.locale, "raw_warning_body"))
        proceed = dialog.addButton(tr(self.locale, "raw_warning_proceed"), QMessageBox.AcceptRole)
        dialog.addButton(tr(self.locale, "raw_warning_cancel"), QMessageBox.RejectRole)
        dialog.setDefaultButton(proceed)
        dialog.exec()
        return dialog.clickedButton() is proceed

    def _arm_session_worker(self, worker: QThread) -> None:
        """Register a QThread that reads/writes the session file; pair with ``finished`` cleanup."""

        self._workers.add(worker)
        self._active_session_worker = worker

        def _on_worker_finished(w: QThread = worker) -> None:
            self._workers.discard(w)
            if self._active_session_worker is w:
                self._active_session_worker = None

        worker.finished.connect(_on_worker_finished)

    def _start_worker(self, worker: QThread, on_success, *, loading_message: str | None = None) -> None:
        if self._active_session_worker is not None and self._active_session_worker.isRunning():
            self.show_toast(tr(self.locale, "worker_session_busy"), "info")
            return
        self._arm_session_worker(worker)

        if self.stack.currentWidget() is self.report_screen:
            self.report_screen.set_busy(True, loading_message or tr(self.locale, "loading"))
            self.report_screen.set_status_message(loading_message or "")
        if hasattr(worker, "progress"):
            worker.progress.connect(self._on_worker_progress)
        worker.result.connect(on_success)
        worker.error.connect(lambda message: self._handle_worker_error(message, worker))
        worker.start()

    def _on_worker_progress(self, message: str) -> None:
        if self.stack.currentWidget() is self.report_screen:
            self.report_screen.set_status_message(message)

    def _handle_worker_error(self, message: str, worker: QThread) -> None:
        self._workers.discard(worker)
        self.report_screen.set_busy(False)
        self.report_screen.set_status_message("")
        if message == get_error("cannot_delete_system_field", self.locale):
            self.show_toast(message, "warning")
            return
        self.show_toast(message, "danger")

    def _resync_filesystem_dates(self, report: FileReport) -> None:
        """Re-apply spoofed FS dates after any file read/write resets them."""

        if self.session is None or self.session.spoofed_dates_anchor is None:
            return
        try:
            set_filesystem_dates(report.path, self.session.spoofed_dates_anchor)
            fmt = self.session.spoofed_dates_anchor.strftime("%Y:%m:%d %H:%M:%S")
            for f in report.fields:
                if f.key in _SYSTEM_DATE_KEYS:
                    f.value = fmt
            self._record_session_changes(set(_SYSTEM_DATE_KEYS), "spoofed")
        except Exception:
            pass

    def _refresh_after_operation(
        self,
        path: Path,
        *,
        changed_keys: set[str] | None = None,
        state: str | None = None,
        toast_message: str | None = None,
        close_editor: bool = True,
    ) -> None:
        self._record_session_changes(changed_keys, state or "")
        if self.session is not None and state in {"spoofed", "removed"}:
            self.session.is_modified = True
            self._update_topbar_context()

        def on_success(report: FileReport) -> None:
            self.report_screen.set_busy(False)
            self.report_screen.set_status_message("")
            if close_editor:
                self.selected_field_key = None
                self.report_screen.close_editor()
            self._resync_filesystem_dates(report)
            self.show_report_screen(report)
            if toast_message:
                self.show_toast(toast_message, "success")

        worker = WorkerThread(lambda: analyzer.analyze(path), self.locale, self)
        self._start_worker(worker, on_success, loading_message=tr(self.locale, "loading"))

    def remove_all_metadata(self) -> None:
        if self.current_report is None:
            return
        if not self._confirm_raw_operation():
            return
        removed_keys = {field.key for field in self.current_report.fields if not field.is_computed}

        def on_success(path: Path) -> None:
            self._refresh_after_operation(path, changed_keys=removed_keys, state="removed", toast_message=tr(self.locale, "field_removed"))

        output_path = self.session.work_path if self.session is not None else None
        worker = WorkerThread(lambda: remove_all(self.current_report, output_path=output_path), self.locale, self)
        self._start_worker(worker, on_success, loading_message=tr(self.locale, "loading"))

    def clean_residual_fields(self) -> None:
        if self.current_report is None or self.session is None:
            return

        logging.debug("=== BEFORE CLEAN RESIDUAL ===")
        logging.debug("session.spoofed_keys: %s", self.session.spoofed_keys)
        logging.debug("session.removed_keys: %s", self.session.removed_keys)
        logging.debug("Device fields in report:")
        spoofed_categories_diag: set[str] = set()
        for f in self.current_report.fields:
            aliases = _field_aliases(f)
            if aliases & self.session.spoofed_keys or f.status == "spoofed":
                spoofed_categories_diag.add(f.category)
            if f.category == "device":
                in_spoofed = bool(aliases & self.session.spoofed_keys)
                logging.debug(
                    "  key=%r label=%r status=%r is_sensitive=%r aliases=%s in_spoofed=%s",
                    f.key, f.label, f.status, f.is_sensitive, aliases, in_spoofed,
                )
        logging.debug("spoofed_categories (computed): %s", spoofed_categories_diag)

        residual_fields = self._residual_fields()

        logging.debug("residual_fields result: %s", [(f.key, f.category, f.status) for f in residual_fields])

        always_delete_fields = [
            field for field in self.current_report.fields
            if _is_always_delete_field(field)
        ]

        if not residual_fields and not always_delete_fields:
            self._update_clean_residual_visibility()
            if self.session.spoofed_keys:
                self.show_toast(tr(self.locale, "clean_residual_nothing"), "success")
            return

        display_fields = residual_fields + [
            f for f in always_delete_fields
            if f.exiftool_tag not in {r.exiftool_tag for r in residual_fields}
        ]
        lines = "\n".join(f"• {field.label}" for field in display_fields[:12])
        if len(display_fields) > 12:
            lines += "\n• ..."

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(tr(self.locale, "clean_residual_title"))
        dialog.setText(
            f"{tr(self.locale, 'clean_residual_body', n=len(display_fields))}\n{lines}"
        )
        dialog.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        ok_button = dialog.button(QMessageBox.Ok)
        if ok_button is not None:
            ok_button.setText(tr(self.locale, "clean_residual_confirm", n=len(display_fields)))
        cancel_button = dialog.button(QMessageBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Cancel")
        if dialog.exec() != QMessageBox.Ok:
            return

        changed_keys = {field.key for field in display_fields}

        def task() -> Path:
            exiftool = require_exiftool()
            target = self.current_report.path

            has_region = any(_is_region_field(f) for f in always_delete_fields)
            if has_region:
                _nuke_region_blocks(target)

            non_region_ad = [f for f in always_delete_fields if not _is_region_field(f)]
            tags_to_clear: list[str] = []
            for field in residual_fields:
                try:
                    safe = validate_exif_tag(field.exiftool_tag)
                except ValueError:
                    logging.warning(
                        "Skipping residual field: file=%s key=%s tag=%r",
                        target,
                        field.key,
                        field.exiftool_tag,
                    )
                    continue
                tags_to_clear.append(f"-{safe}=")
            seen: set[str] = {field.exiftool_tag for field in residual_fields}
            for field in non_region_ad:
                if field.exiftool_tag not in seen:
                    try:
                        safe = validate_exif_tag(field.exiftool_tag)
                    except ValueError:
                        logging.warning(
                            "Skipping residual field: file=%s key=%s tag=%r",
                            target,
                            field.key,
                            field.exiftool_tag,
                        )
                        continue
                    tags_to_clear.append(f"-{safe}=")
                    seen.add(field.exiftool_tag)

            if tags_to_clear:
                args = [exiftool, "-m"] + tags_to_clear + ["-overwrite_original", str(target)]
                result = subprocess.run(args, capture_output=True, text=True, creationflags=get_subprocess_flags())
                stderr = (result.stderr or "").strip()
                if result.returncode != 0 and not _is_exiftool_warnings_only(stderr):
                    raise RuntimeError(stderr or "Failed to remove residual fields.")

            remove_exiftool_signature(target, exiftool)
            return target

        def on_success(path: Path) -> None:
            self._refresh_after_operation(
                path,
                changed_keys=changed_keys,
                state="removed",
                toast_message=tr(self.locale, "clean_residual_toast", n=len(display_fields)),
            )

        worker = WorkerThread(task, self.locale, self)
        self._start_worker(worker, on_success, loading_message=tr(self.locale, "clean_residual_btn"))

    def smart_spoof_all(self) -> None:
        if self.current_report is None:
            return
        if not self._confirm_raw_operation():
            return
        if not any(field.is_sensitive for field in self.current_report.fields):
            self.show_toast(get_error("spoof_nothing_to_do", self.locale), "warning")
            return
        if self.current_report.file_type == "raw":
            self.show_toast(tr(self.locale, "raw_tip"), "info")

        def on_success(report: FileReport, changes: list[str], info_codes: list[str]) -> None:
            self._on_smart_spoof_complete(report, changes, info_codes)

        worker = SmartSpoofWorker(self.current_report, self.locale, self)
        self._start_worker(worker, on_success, loading_message=tr(self.locale, "progress_gps"))

    def save_copy(self) -> None:
        if self.session is None:
            return
        self._save_session_copy_via_dialog()

    def handle_field_action(self, field: MetaField, mode: str) -> None:
        if mode == "info":
            tip_key = "region_tooltip" if _is_region_field(field) else "computed_tooltip"
            self.show_toast(tr(self.locale, tip_key), "warning")
            return

        if mode == "randomize_fs_date":
            if self.current_report is None:
                return
            target = self.session.work_path if self.session is not None else self.current_report.path
            sys_changed_keys = set(_SYSTEM_DATE_KEYS)

            def on_fs_spoof(path: Path) -> None:
                self._refresh_after_operation(
                    path,
                    changed_keys=sys_changed_keys,
                    state="spoofed",
                    toast_message=tr(self.locale, "applied"),
                )

            worker = WorkerThread(lambda: spoof_filesystem_dates(target), self.locale, self)
            self._start_worker(worker, on_fs_spoof, loading_message=tr(self.locale, "loading"))
            return

        if mode == "remove":
            if self.current_report is None:
                return
            if not self._confirm_raw_operation():
                return

            def on_success(path: Path) -> None:
                if field.key in {"FileModifyDate", "FileAccessDate", "FileCreateDate"}:
                    self._refresh_after_operation(path, close_editor=False)
                    self.show_toast(get_error("cannot_delete_system_field", self.locale), "warning")
                    return
                self._refresh_after_operation(
                    path,
                    changed_keys={field.key},
                    state="removed",
                    toast_message=tr(self.locale, "field_removed"),
                )

            worker = WorkerThread(lambda: remove_field(self.current_report, field.exiftool_tag), self.locale, self)
            self._start_worker(worker, on_success, loading_message=tr(self.locale, "loading"))
            return
        self.selected_field_key = field.key
        self.report_screen.open_editor(field)

    def apply_editor_changes(self, field: MetaField, writes: dict[str, object], display_updates: dict[str, str]) -> None:
        if self.current_report is None:
            return
        if not self._confirm_raw_operation():
            return

        # __dms_system_date__: OS file times, not EXIF — routed to set_filesystem_dates / spoof_filesystem_dates.
        if "__dms_system_date__" in writes:
            date_value = writes["__dms_system_date__"]
            target = self.session.work_path if self.session is not None else self.current_report.path
            sys_changed_keys = set(_SYSTEM_DATE_KEYS)

            def on_sys_date_success(path: Path) -> None:
                self._refresh_after_operation(
                    path,
                    changed_keys=sys_changed_keys,
                    state="spoofed",
                    toast_message=tr(self.locale, "applied"),
                )

            if date_value is None:
                worker = WorkerThread(lambda: spoof_filesystem_dates(target), self.locale, self)
            else:
                parsed = parse_metadata_datetime(str(date_value))
                if parsed is not None:
                    worker = WorkerThread(lambda d=parsed: set_filesystem_dates(target, d), self.locale, self)
                else:
                    worker = WorkerThread(lambda: spoof_filesystem_dates(target), self.locale, self)

            self._start_worker(worker, on_sys_date_success, loading_message=tr(self.locale, "loading"))
            return

        if field.category == "dates" and writes.get("__dms_date_kind__") == "dates":
            changed_keys = {item.key for item in self.current_report.fields if item.category == "dates"}
        else:
            changed_keys = set(display_updates) | {tag.split(".")[-1].split(":")[-1] for tag in writes}

        def on_success(path: Path) -> None:
            toast = tr(self.locale, "gps_spoofed") if field.category == "gps" else tr(self.locale, "applied")
            self._refresh_after_operation(path, changed_keys=changed_keys, state="spoofed", toast_message=toast)

        worker = WorkerThread(lambda: apply_field_spoof(self.current_report, field, writes), self.locale, self)
        self._start_worker(worker, on_success, loading_message=tr(self.locale, "loading"))

    def close_editor(self) -> None:
        self.selected_field_key = None
        self.report_screen.close_editor()

    def _show_editor_error(self, key: str) -> None:
        self.show_toast(get_error(key, self.locale), "warning")

    def _smart_spoof_changed_keys(self, report: FileReport, changes: list[str]) -> set[str]:
        changed_keys: set[str] = set()
        for field in report.fields:
            if "gps" in changes and field.category == "gps":
                changed_keys.add(field.key)
            if "device" in changes and field.category == "device":
                changed_keys.add(field.key)
            if "dates" in changes and field.category == "dates":
                changed_keys.add(field.key)
            if "author" in changes and field.category == "author":
                changed_keys.add(field.key)
            if "software" in changes and "software" in field.key.lower():
                changed_keys.add(field.key)
        return changed_keys

    def _on_smart_spoof_complete(self, new_report: FileReport, changes: list[str], info_codes: list[str]) -> None:
        change_labels = {
            "en": {
                "gps": "GPS location",
                "device": "Device model",
                "dates": "Dates",
                "author": "Author",
                "software": "Software",
            },
            "ru": {
                "gps": "GPS локация",
                "device": "Модель устройства",
                "dates": "Даты",
                "author": "Автор",
                "software": "Программа",
            },
            "zh": {
                "gps": "GPS位置",
                "device": "设备型号",
                "dates": "日期",
                "author": "作者",
                "software": "软件",
            },
        }
        summary = {
            "en": "Spoofed: {items}",
            "ru": "Подменено: {items}",
            "zh": "已替换: {items}",
        }

        self.report_screen.set_busy(False)
        self.report_screen.set_status_message("")
        changed_keys = self._smart_spoof_changed_keys(new_report, changes)
        self._record_session_changes(changed_keys, "spoofed")
        if self.session is not None:
            logging.debug("=== AFTER SMART SPOOF ===")
            logging.debug("changes list from apply_smart_spoof: %s", changes)
            logging.debug("changed_keys passed to _record_session_changes: %s", changed_keys)
            logging.debug("session.spoofed_keys (full): %s", self.session.spoofed_keys)
        if self.session is not None and changes:
            self.session.is_modified = True
            if "dates" in changes:
                for f in new_report.fields:
                    if f.category == "dates" and f.key not in _SYSTEM_DATE_KEYS:
                        dt = parse_metadata_datetime(f.value)
                        if dt is not None:
                            self.session.spoofed_dates_anchor = dt
                            break
        self.selected_field_key = None
        self.report_screen.close_editor()
        self._resync_filesystem_dates(new_report)
        self.show_report_screen(new_report)

        for code in info_codes:
            self.show_toast(tr(self.locale, code), "info")

        if not changes:
            if not info_codes:
                self.show_toast(get_error("spoof_nothing_to_do", self.locale), "warning")
            return

        labels = change_labels.get(self.locale, change_labels["en"])
        changed_items = [labels[item] for item in changes if item in labels]
        message = summary.get(self.locale, summary["en"]).format(items=", ".join(changed_items))
        self.show_toast(message, "success")

    def show_toast(self, message: str, kind: str = "success") -> None:
        toast = Toast(parent=self.centralWidget())
        toast.dismissed.connect(self._on_toast_dismissed)
        self._active_toasts.append(toast)
        target = self._layout_toasts(new_toast=toast)
        toast.show_message(message, kind, target)
        self._layout_toasts()

    def _layout_toasts(self, new_toast: Toast | None = None) -> QPoint:
        parent = self.centralWidget()
        if parent is None:
            return QPoint(0, 0)
        parent_origin = parent.mapToGlobal(QPoint(0, 0))
        right = parent_origin.x() + parent.width() - 20
        bottom = parent_origin.y() + parent.height() - 20

        # Clamp to screen: layered toasts off by one pixel break UpdateLayeredWindowIndirect on Windows.
        screen = QGuiApplication.screenAt(parent_origin) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None

        offset = 0
        new_target = QPoint(0, 0)
        for index, toast in enumerate(reversed(self._active_toasts)):
            if toast is not new_toast:
                toast.adjustSize()
            x = right - toast.width()
            y = bottom - toast.height() - offset
            if available is not None:
                x = max(available.left(), min(x, available.right() - toast.width()))
                y = max(available.top(), min(y, available.bottom() - toast.height()))
            target = QPoint(x, y)
            if toast is not new_toast:
                toast.reposition(target)
            if index == 0:
                new_target = target
            offset += toast.height() + 8
        return new_target

    def _on_toast_dismissed(self, toast: Toast) -> None:
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)
            self._layout_toasts()

    def _update_topbar_context(self) -> None:
        current = self.stack.currentWidget()
        if current is self.batch_screen:
            self.back_button.show()
            self.compare_button.hide()
            self.title_label.setText(f"{len(self.batch_sessions)} files")
            self.report_screen.set_modified_state(False)
            return
        if current is self.compare_screen:
            self.back_button.show()
            self.compare_button.hide()
            title = tr(self.locale, "compare_title")
            if self.session is not None:
                title = f"{title}: {self.session.original_path.name}"
                self.report_screen.set_modified_state(self.session.is_modified)
            else:
                self.report_screen.set_modified_state(False)
            self.title_label.setText(title)
            return
        if self.session is None:
            self.back_button.setVisible(current is not self.drop_screen)
            self.compare_button.hide()
            self.title_label.setText(tr(self.locale, "app_title"))
            self.report_screen.set_modified_state(False)
            return
        self.back_button.show()
        self.compare_button.setVisible(current is self.report_screen and self.session.is_modified)
        self.compare_button.setEnabled(self.session.is_modified)
        label = self.session.original_path.name
        self.title_label.setText(f"{label} {'●' if self.session.is_modified else ''}".strip())
        self.report_screen.set_modified_state(self.session.is_modified)

    def _cleanup_session_files(self) -> None:
        if self.session is not None and self.session.temp_dir is not None:
            shutil.rmtree(self.session.temp_dir, ignore_errors=True)
        self.session = None

    def _cleanup_batch_sessions(self) -> None:
        for session in self.batch_sessions:
            if session.temp_dir is not None:
                shutil.rmtree(session.temp_dir, ignore_errors=True)
        self.batch_sessions = []

    def _session_belongs_to_batch(self) -> bool:
        return self.session is not None and any(item.work_path == self.session.work_path for item in self.batch_sessions)

    def _create_temp_session(self, path: Path) -> FileSession:
        temp_dir = Path(tempfile.mkdtemp(prefix="dms_"))
        work_path = temp_dir / f"{path.stem}_cleaned{path.suffix}"
        shutil.copy2(path, work_path)
        empty_report = FileReport(path=work_path, file_type=path.suffix.lower().lstrip("."), fields=[], thumbnail=None)
        return FileSession(
            original_path=path,
            work_path=work_path,
            original_report=copy.deepcopy(empty_report),
            current_report=empty_report,
            temp_dir=temp_dir,
        )

    def _batch_modified_sessions(self) -> list[FileSession]:
        return [session for session in self.batch_sessions if session.is_modified]

    def _guard_batch_unsaved_changes(self) -> bool:
        modified = self._batch_modified_sessions()
        if not modified:
            return True
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(tr(self.locale, "unsaved_title"))
        dialog.setText(tr(self.locale, "unsaved_body"))
        discard = dialog.addButton(tr(self.locale, "unsaved_discard"), QMessageBox.DestructiveRole)
        save_first = dialog.addButton(tr(self.locale, "unsaved_save_first"), QMessageBox.AcceptRole)
        dialog.addButton(tr(self.locale, "unsaved_cancel"), QMessageBox.RejectRole)
        dialog.setDefaultButton(save_first)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is discard:
            return True
        if clicked is save_first:
            return self.save_all_batch()
        return False

    def _guard_navigation_loss(self) -> bool:
        current = self.stack.currentWidget()
        if current is self.compare_screen:
            current = self.report_screen
        if current is self.batch_screen:
            return self._guard_batch_unsaved_changes()
        if current is self.report_screen and not self._session_belongs_to_batch():
            return self._guard_unsaved_changes()
        return True

    def navigate_back(self) -> None:
        current = self.stack.currentWidget()
        if current is self.compare_screen:
            self.show_report_from_compare()
            return
        if current is self.report_screen and self._session_belongs_to_batch():
            self.report_screen.set_status_message("")
            self.report_screen.close_editor()
            self.stack.setCurrentWidget(self.batch_screen)
            self._update_topbar_context()
            return
        if current is self.batch_screen:
            if not self._guard_batch_unsaved_changes():
                return
            self._cleanup_batch_sessions()
            self.current_report = None
            self.field_states = {}
            self.selected_field_key = None
            self.stack.setCurrentWidget(self.drop_screen)
            self.drop_screen.set_drag_active(False)
            self.back_button.hide()
            self.compare_button.hide()
            self._update_topbar_context()
            return
        self.show_drop_screen()

    def _filter_dms_output_files(self, paths: list[Path]) -> list[Path] | None:
        normal: list[Path] = []
        suspicious: list[Path] = []
        for p in paths:
            (suspicious if looks_like_dms_output(p) else normal).append(p)
        if not suspicious:
            return normal
        dialog = DMSOutputWarningDialog(suspicious, self.locale, parent=self)
        dialog.exec()
        if dialog.result_action == DMSOutputWarningDialog.CANCEL:
            return None
        if dialog.result_action == DMSOutputWarningDialog.ADD:
            return normal + suspicious
        return normal

    def open_files(self, paths: list[Path]) -> None:
        clean_paths = [Path(path) for path in paths if Path(path).exists() and Path(path).is_file()]
        if not clean_paths:
            return
        if not self._guard_navigation_loss():
            return
        filtered = self._filter_dms_output_files(clean_paths)
        if filtered is None or not filtered:
            return
        if len(filtered) == 1:
            self.open_single_file(filtered[0])
        else:
            self.open_batch(filtered)

    def open_single_file(self, path: Path) -> None:
        self.load_file(path)

    def open_batch(self, paths: list[Path]) -> None:
        self._cleanup_session_files()
        self._cleanup_batch_sessions()
        self.current_report = None
        self.field_states = {}
        self.selected_field_key = None
        self.batch_sessions = [self._create_temp_session(path) for path in paths]
        self.batch_screen.set_files([session.original_path for session in self.batch_sessions])
        self.stack.setCurrentWidget(self.batch_screen)
        self._update_topbar_context()

    def add_more_batch_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(self, tr(self.locale, "browse_file"), "", _FILE_DIALOG_FILTER)
        if not filenames:
            return
        raw_paths = [Path(name) for name in filenames]
        filtered = self._filter_dms_output_files(raw_paths)
        if filtered is None or not filtered:
            return
        new_sessions = [self._create_temp_session(path) for path in filtered]
        self.batch_sessions.extend(new_sessions)
        self.batch_screen.append_files([session.original_path for session in new_sessions])
        self._update_topbar_context()

    def remove_batch_item(self, index: int) -> None:
        if not (0 <= index < len(self.batch_sessions)):
            return
        session = self.batch_sessions.pop(index)
        if session.temp_dir is not None:
            shutil.rmtree(session.temp_dir, ignore_errors=True)
        self.batch_screen.remove_index(index)
        self._update_topbar_context()

    def _update_batch_session_states(self, session: FileSession) -> None:
        _populate_session_keys(session)

    def process_batch(self, mode: str) -> None:
        if not self.batch_sessions:
            return
        worker = BatchWorker(self.batch_sessions, mode, self.locale, self)
        self._batch_worker = worker
        self._workers.add(worker)
        self.batch_screen.set_processing(True)
        self.batch_screen.set_all_done(False)
        worker.file_started.connect(self.batch_screen.update_started)
        worker.file_analyzed.connect(self.batch_screen.update_analyzed)
        worker.file_risk_updated.connect(self.batch_screen.update_risk)
        worker.file_progress.connect(self.batch_screen.update_progress)
        worker.file_done.connect(self.batch_screen.update_done)

        def on_complete(success_count: int, fail_count: int) -> None:
            self._workers.discard(worker)
            self.batch_screen.set_processing(False)
            for session in self.batch_sessions:
                # Recover empty key sets if a batch step failed before _populate_session_keys ran.
                if session.is_modified and not session.spoofed_keys and not session.removed_keys:
                    self._update_batch_session_states(session)
                    self.session = session
                    self._apply_session_states(session.current_report)
            self.session = None
            self.batch_screen.set_all_done(success_count > 0)
            self.show_toast(tr(self.locale, "batch_complete", n=success_count + fail_count), "success" if fail_count == 0 else "warning")
            self._update_topbar_context()

        worker.error.connect(lambda message: self.show_toast(message, "danger"))
        worker.all_done.connect(on_complete)
        worker.finished.connect(lambda: self._workers.discard(worker))
        worker.finished.connect(lambda: self.batch_screen.set_processing(False))
        worker.finished.connect(lambda: setattr(self, "_batch_worker", None))
        worker.start()

    def save_all_batch(self) -> bool:
        modified = [session for session in self.batch_sessions if session.is_modified]
        if not modified:
            return False
        folder = QFileDialog.getExistingDirectory(self, tr(self.locale, "batch_save_all"))
        if not folder:
            return False
        output_dir = Path(folder)
        for session in modified:
            destination = output_dir / f"{session.original_path.stem}_cleaned{session.original_path.suffix}"
            shutil.copy2(session.work_path, destination)
            session.is_modified = False
        self.batch_screen.set_all_done(True)
        self._update_topbar_context()
        self.show_toast(f"Saved {len(modified)} files to: {output_dir}", "success")
        return True

    def open_batch_item(self, index: int) -> None:
        if not (0 <= index < len(self.batch_sessions)):
            return
        session = self.batch_sessions[index]
        if not session.is_modified and not session.current_report.fields:
            return
        self.session = session
        self.show_report_screen(session.current_report)

    def show_compare(self) -> None:
        if self.session is None or not self.session.is_modified:
            return
        cleaned_report = copy.deepcopy(self.session.current_report)
        original_report = copy.deepcopy(self.session.original_report)
        self._apply_session_states(cleaned_report)
        self.compare_screen.set_reports(original_report, cleaned_report)
        self.stack.setCurrentWidget(self.compare_screen)
        self._update_topbar_context()

    def show_report_from_compare(self) -> None:
        if self.session is None:
            return
        self.show_report_screen(self.session.current_report)

    def show_drop_screen(self) -> None:
        if not self._guard_navigation_loss():
            return
        if self.stack.currentWidget() is self.batch_screen or self._session_belongs_to_batch():
            self._cleanup_batch_sessions()
        else:
            self._cleanup_session_files()
        self.session = None
        self.current_report = None
        self.field_states = {}
        self.selected_field_key = None
        self.back_button.hide()
        self.compare_button.hide()
        self.report_screen.set_status_message("")
        self.report_screen.close_editor()
        self.stack.setCurrentWidget(self.drop_screen)
        self.drop_screen.set_drag_active(False)
        self._update_topbar_context()

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI interaction
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self.stack.currentWidget() is self.drop_screen:
                self.drop_screen.set_drag_active(True)
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # pragma: no cover - GUI interaction
        self.drop_screen.set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # pragma: no cover - GUI interaction
        self.drop_screen.set_drag_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_files(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def browse_file(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(self, tr(self.locale, "browse_file"), "", _FILE_DIALOG_FILTER)
        if filenames:
            self.open_files([Path(name) for name in filenames])

    def load_file(self, path: Path) -> None:
        self._cleanup_batch_sessions()
        self._cleanup_session_files()
        self.current_report = None
        self.field_states = {}
        self.selected_field_key = None
        self._update_topbar_context()

        if self._active_session_worker is not None and self._active_session_worker.isRunning():
            self.show_toast(tr(self.locale, "worker_session_busy"), "info")
            return

        session = self._create_temp_session(path)
        worker = WorkerThread(lambda: analyzer.analyze(session.work_path), self.locale, self)
        self._arm_session_worker(worker)
        self.report_screen.set_busy(True, tr(self.locale, "loading"))
        self.report_screen.set_status_message(tr(self.locale, "loading"))
        worker.result.connect(lambda report, current=session, current_worker=worker: self._on_report_ready(current.original_path, current.work_path, current.temp_dir, report))
        worker.error.connect(lambda message, tmp=session.temp_dir, current=worker: self._handle_load_error(message, tmp, current))
        worker.start()

    def _handle_load_error(self, message: str, temp_dir: Path, worker: QThread) -> None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        self._handle_worker_error(message, worker)

    def _on_report_ready(self, original_path: Path, work_path: Path, temp_dir: Path, report: FileReport) -> None:
        self.report_screen.set_busy(False)
        self.report_screen.set_status_message("")
        self.session = FileSession(
            original_path=original_path,
            work_path=work_path,
            original_report=copy.deepcopy(report),
            current_report=report,
            temp_dir=temp_dir,
        )
        self.show_report_screen(report)

    def closeEvent(self, event) -> None:  # pragma: no cover - GUI interaction
        if not self._guard_navigation_loss():
            event.ignore()
            return
        for worker in list(self._workers):
            worker.requestInterruption()
        for worker in list(self._workers):
            if not worker.wait(_CLOSE_JOIN_TIMEOUT_MS):
                logging.warning(
                    "QThread did not finish within %s ms after interruption: %s",
                    _CLOSE_JOIN_TIMEOUT_MS,
                    worker,
                )
        self._workers.clear()
        self._batch_worker = None
        self._cleanup_batch_sessions()
        self._cleanup_session_files()
        super().closeEvent(event)


def _get_app_icon() -> QIcon:
    # Prefer icon.ico (multi-size) for Windows shell; else SVG. Frozen: assets under _MEIPASS.
    from dms.config import DATA_DIR

    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) / "dms" / "data"  # type: ignore[attr-defined]
    else:
        base = DATA_DIR

    for name in ("icon.ico", "icon.svg"):
        candidate = base / name
        if candidate.exists():
            return QIcon(str(candidate))

    return QIcon()


def _apply_dark_palette(app: QApplication) -> None:
    """Force dark palette so system light themes cannot override text/background colors."""

    palette = QPalette()
    group = QPalette.ColorGroup.All
    palette.setColor(group, QPalette.ColorRole.Window, QColor("#0d0d1a"))
    palette.setColor(group, QPalette.ColorRole.WindowText, QColor("#f8fafc"))
    palette.setColor(group, QPalette.ColorRole.Base, QColor("#1a1a2e"))
    palette.setColor(group, QPalette.ColorRole.Text, QColor("#f8fafc"))
    palette.setColor(group, QPalette.ColorRole.Button, QColor("#1a1a2e"))
    palette.setColor(group, QPalette.ColorRole.ButtonText, QColor("#f8fafc"))
    app.setPalette(palette)


def main() -> None:
    """Qt entrypoint for the desktop app."""

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    configure_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    # Stable style across Windows versions; avoids odd window-decoration behavior with some themes.
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(GLOBAL_QSS)
    app.setWindowIcon(_get_app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
