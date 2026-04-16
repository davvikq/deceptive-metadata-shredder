"""Batch processing screen."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dms.interfaces.gui.theme import COLORS, tr
from dms.interfaces.gui.widgets.glass_card import GlassCard


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def _format_icon(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".heic"}:
        return "🖼"
    if suffix in {".pdf", ".docx"}:
        return "📄"
    if suffix in {".mp4", ".mov"}:
        return "🎬"
    return "📦"


class BatchFileCard(GlassCard):
    removeRequested = Signal(int)
    openRequested = Signal(int)

    def __init__(self, index: int, path: Path, parent=None):
        super().__init__(parent)
        self.index = index
        self.path = path
        self._status = "ready"
        self._done = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        layout.addLayout(top)

        self.icon_label = QLabel(_format_icon(path), self)
        self.icon_label.setFont(QFont("Segoe UI Emoji", 18))
        top.addWidget(self.icon_label)

        self.name_label = QLabel(path.name, self)
        self.name_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        top.addWidget(self.name_label, 1)

        try:
            size_text = _format_bytes(path.stat().st_size)
        except OSError:
            size_text = "—"
        self.size_label = QLabel(size_text, self)
        self.size_label.setFont(QFont("Segoe UI", 10))
        self.size_label.setStyleSheet(f"color:{COLORS['text_secondary']};")
        top.addWidget(self.size_label)

        self.risk_label = QLabel("", self)
        self.risk_label.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.risk_label.setStyleSheet(f"color:{COLORS['warning']};")
        self.risk_label.hide()
        top.addWidget(self.risk_label)

        self.remove_button = QPushButton("×", self)
        self.remove_button.setFixedSize(28, 28)
        self.remove_button.clicked.connect(lambda: self.removeRequested.emit(self.index))
        top.addWidget(self.remove_button)
        self.remove_button.setText("X")
        self.remove_button.setObjectName("btn_remove_file")
        self.remove_button.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.remove_button.setStyleSheet(
            "QPushButton#btn_remove_file {"
            "color: #94a3b8; background: transparent; border: none; border-radius: 6px;"
            "min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;"
            "}"
            "QPushButton#btn_remove_file:hover { background: rgba(239, 68, 68, 0.2); color: #ef4444; }"
        )

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self._ready_progress_style = (
            "QProgressBar { background: transparent; border: 1px dashed rgba(99,102,241,0.25); "
            "border-radius: 3px; color: #f8fafc; }"
            "QProgressBar::chunk { background: transparent; border-radius: 3px; }"
        )
        self._active_progress_style = (
            "QProgressBar { background: rgba(255,255,255,0.06); border: none; border-radius: 3px; color: #f8fafc; }"
            f"QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 3px; }}"
        )
        self.progress.setStyleSheet(self._ready_progress_style)
        layout.addWidget(self.progress)

        self.status_label = QLabel(self)
        self.status_label.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.status_label.setStyleSheet(f"color:{COLORS['text_secondary']};")
        layout.addWidget(self.status_label)

    def refresh_text(self, locale: str) -> None:
        metrics = QFontMetrics(self.name_label.font())
        self.name_label.setText(metrics.elidedText(self.path.name, Qt.ElideRight, 420))
        labels = {
            "ready": tr(locale, "batch_ready"),
            "waiting": tr(locale, "batch_waiting"),
            "analyzing": tr(locale, "batch_analyzing"),
            "processing": tr(locale, "batch_processing"),
            "done": tr(locale, "batch_done"),
            "error": tr(locale, "batch_error"),
        }
        colors = {
            "ready": COLORS["accent"],
            "waiting": COLORS["text_secondary"],
            "analyzing": "#06b6d4",
            "processing": COLORS["warning"],
            "done": COLORS["success"],
            "error": COLORS["danger"],
        }
        self.status_label.setText(labels.get(self._status, labels["ready"]))
        self.status_label.setStyleSheet(f"color:{colors.get(self._status, COLORS['text_secondary'])};")

    def set_risk(self, count: int) -> None:
        self.risk_label.setText(f"⚠ {count} fields")
        self.risk_label.setVisible(True)

    def set_progress(self, percent: int) -> None:
        self.progress.setValue(percent)

    def update_risk(self, count: int) -> None:
        if count <= 0:
            self.risk_label.setText("✓ Clean")
            self.risk_label.setStyleSheet(f"color:{COLORS['success']};")
        elif count <= 3:
            self.risk_label.setText(f"▲ {count} fields")
            self.risk_label.setStyleSheet(f"color:{COLORS['warning']};")
        else:
            self.risk_label.setText(f"▲ {count} fields")
            self.risk_label.setStyleSheet(f"color:{COLORS['danger']};")
        self.risk_label.setVisible(True)

    def set_status(self, status: str) -> None:
        self._status = status
        self._done = status == "done"
        self.remove_button.setVisible(status == "ready")
        self.progress.setStyleSheet(self._ready_progress_style if status == "ready" else self._active_progress_style)
        self.refresh_text(self.property("locale") or "en")

    def mousePressEvent(self, event) -> None:  # pragma: no cover - UI interaction
        if self._done and event.button() == Qt.LeftButton:
            self.openRequested.emit(self.index)
        super().mousePressEvent(event)


class ScreenBatch(QWidget):
    """Batch file list and process controls."""

    backRequested = Signal()
    addMoreRequested = Signal()
    processRequested = Signal(str)
    saveAllRequested = Signal()
    removeItemRequested = Signal(int)
    openItemRequested = Signal(int)

    def __init__(self, locale_getter, parent=None):
        super().__init__(parent)
        self.locale_getter = locale_getter
        self.cards: list[BatchFileCard] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header_label = QLabel(self)
        self.header_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        root.addWidget(self.header_label)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.scroll, 1)

        self.container = QWidget(self.scroll)
        self.scroll.setWidget(self.container)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(10)
        self.container_layout.addStretch(1)

        self.hint_label = QLabel(self)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setFont(QFont("Segoe UI", 11))
        self.hint_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-style: italic;")
        root.addWidget(self.hint_label)

        self.add_more_button = QPushButton(self)
        self.add_more_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.add_more_button.setStyleSheet("QPushButton { border-style: dashed; }")
        self.add_more_button.clicked.connect(self.addMoreRequested)
        root.addWidget(self.add_more_button, alignment=Qt.AlignLeft)

        self.footer = GlassCard(self)
        self.footer.setMinimumHeight(96)
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(10)
        root.addWidget(self.footer)

        mode_row = QHBoxLayout()
        footer_layout.addLayout(mode_row)
        self.mode_label = QLabel(self.footer)
        self.mode_label.setFont(QFont("Segoe UI", 10, QFont.Medium))
        mode_row.addWidget(self.mode_label)
        self.mode_group = QButtonGroup(self.footer)
        self.radio_remove = QRadioButton(self.footer)
        self.radio_spoof = QRadioButton(self.footer)
        self.radio_spoof_clean = QRadioButton(self.footer)
        for button in (self.radio_remove, self.radio_spoof, self.radio_spoof_clean):
            button.setFont(QFont("Segoe UI", 10))
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        self.radio_spoof.setChecked(True)
        mode_row.addStretch(1)

        btn_row = QHBoxLayout()
        footer_layout.addLayout(btn_row)
        btn_row.addStretch(1)
        self.btn_apply = QPushButton(self.footer)
        self.btn_apply.clicked.connect(lambda: self.processRequested.emit(self.get_selected_mode()))
        self.btn_apply.setStyleSheet(
            "QPushButton { background: #6366f1; color: #f8fafc; border: 1px solid #6366f1; border-radius: 10px; "
            "padding: 0 20px; min-height: 36px; }"
            "QPushButton:disabled { background: rgba(99,102,241,0.35); color: rgba(255,255,255,0.75); "
            "border: 1px solid rgba(99,102,241,0.35); }"
        )
        btn_row.addWidget(self.btn_apply)
        self.btn_save_all = QPushButton(self.footer)
        self.btn_save_all.clicked.connect(self.saveAllRequested)
        self.btn_save_all.setEnabled(False)
        self.btn_save_all.setStyleSheet(
            "QPushButton { background: #22c55e; color: #f8fafc; border: 1px solid #22c55e; border-radius: 10px; "
            "padding: 0 20px; min-height: 36px; }"
            "QPushButton:disabled { background: rgba(34,197,94,0.25); color: rgba(255,255,255,0.65); "
            "border: 1px solid rgba(34,197,94,0.35); }"
        )
        btn_row.addWidget(self.btn_save_all)

        self.refresh_locale()

    def get_selected_mode(self) -> str:
        if self.radio_remove.isChecked():
            return "remove"
        if self.radio_spoof_clean.isChecked():
            return "spoof_clean"
        return "spoof"

    def refresh_locale(self) -> None:
        locale = self.locale_getter()
        self.header_label.setText(tr(locale, "batch_title"))
        self.add_more_button.setText(tr(locale, "batch_add_more"))
        self.mode_label.setText("Mode:")
        self.radio_remove.setText(tr(locale, "mode_remove"))
        self.radio_spoof.setText(tr(locale, "mode_spoof"))
        self.radio_spoof_clean.setText(tr(locale, "mode_spoof_clean"))
        self.btn_apply.setText(tr(locale, "batch_processing_btn") if not self.btn_apply.isEnabled() else tr(locale, "batch_apply"))
        self.btn_save_all.setText(tr(locale, "batch_save_all"))
        for card in self.cards:
            card.setProperty("locale", locale)
            card.refresh_text(locale)
        self.hint_label.setText(tr(locale, "batch_hint"))
        self.hint_label.setVisible(bool(self.cards) and all(card._status == "ready" for card in self.cards))

    def set_files(self, paths: list[Path]) -> None:
        while self.container_layout.count() > 1:
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = []
        locale = self.locale_getter()
        for index, path in enumerate(paths):
            card = BatchFileCard(index, path, self.container)
            card.setProperty("locale", locale)
            card.refresh_text(locale)
            card.removeRequested.connect(self.removeItemRequested)
            card.openRequested.connect(self.openItemRequested)
            self.cards.append(card)
            self.container_layout.insertWidget(self.container_layout.count() - 1, card)
        self.header_label.setText(f"{len(paths)} files")
        self.btn_save_all.setEnabled(False)
        self.hint_label.setVisible(bool(paths))

    def append_files(self, paths: list[Path]) -> None:
        current = [card.path for card in self.cards]
        self.set_files(current + paths)

    def remove_index(self, index: int) -> None:
        if 0 <= index < len(self.cards):
            card = self.cards.pop(index)
            card.deleteLater()
            for idx, item in enumerate(self.cards):
                item.index = idx
            self.header_label.setText(f"{len(self.cards)} files")
            self.hint_label.setVisible(bool(self.cards) and all(card._status == "ready" for card in self.cards))

    def update_started(self, index: int) -> None:
        if 0 <= index < len(self.cards):
            self.cards[index].set_status("analyzing")
            self.hint_label.hide()

    def update_analyzed(self, index: int, sensitive_count: int) -> None:
        if 0 <= index < len(self.cards):
            self.cards[index].set_risk(sensitive_count)

    def update_progress(self, index: int, percent: int) -> None:
        if 0 <= index < len(self.cards):
            card = self.cards[index]
            if percent >= 30 and card._status == "analyzing":
                card.set_status("processing")
            card.set_progress(percent)

    def update_done(self, index: int, success: bool) -> None:
        if 0 <= index < len(self.cards):
            self.cards[index].set_status("done" if success else "error")

    def update_risk(self, index: int, risk_count: int) -> None:
        if 0 <= index < len(self.cards):
            self.cards[index].update_risk(risk_count)

    def set_all_done(self, enabled: bool) -> None:
        self.btn_save_all.setEnabled(enabled)

    def set_processing(self, processing: bool) -> None:
        self.btn_apply.setEnabled(not processing)
        self.btn_apply.setText(
            tr(self.locale_getter(), "batch_processing_btn") if processing else tr(self.locale_getter(), "batch_apply")
        )
