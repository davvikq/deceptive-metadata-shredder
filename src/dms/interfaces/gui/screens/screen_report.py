"""Main report screen."""

from __future__ import annotations

import io
from pathlib import Path

from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from dms.core.models import FileReport, MetaField
from dms.interfaces.gui.theme import COLORS, risk_state, tr
from dms.interfaces.gui.widgets.glass_card import GlassCard
from dms.interfaces.gui.widgets.meta_table import MetaTable
from dms.interfaces.gui.widgets.spoof_editor import SpoofEditor
from dms.interfaces.gui.widgets.tag_badge import TagBadge


class RiskWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.count = 0
        self.color = COLORS["success"]
        self.setMinimumSize(96, 96)
        self._font = QFont("Segoe UI", 18, QFont.Bold)

    def set_state(self, count: int, color: str) -> None:
        self.count = count
        self.color = color
        self.update()

    def paintEvent(self, _event) -> None:  # pragma: no cover - paint only
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(10, 10, -10, -10)
        pen = QPen(QColor("#293043"))
        pen.setWidth(7)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -360 * 16)
        pen.setColor(QColor(self.color))
        painter.setPen(pen)
        span = 360 if self.count == 0 else min(360, self.count * 30)
        painter.drawArc(rect, 90 * 16, -span * 16)
        painter.setPen(QColor("#f8fafc"))
        painter.setFont(self._font)
        painter.drawText(self.rect(), Qt.AlignCenter, str(self.count))


class AnimatedSidePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel_width = 0
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.animation = QPropertyAnimation(self, b"panelWidth", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def get_panel_width(self) -> int:
        return self._panel_width

    def set_panel_width(self, value: int) -> None:
        self._panel_width = value
        self.setMinimumWidth(value)
        self.setMaximumWidth(value)

    panelWidth = Property(int, get_panel_width, set_panel_width)

    def reveal(self, visible: bool) -> None:
        self.animation.stop()
        self.animation.setStartValue(self._panel_width)
        self.animation.setEndValue(300 if visible else 0)
        self.animation.start()


class ScreenReport(QWidget):
    """Report view: preview, metadata tree, spoof editor."""

    removeAllRequested = Signal()
    smartSpoofRequested = Signal()
    saveRequested = Signal()
    cleanResidualRequested = Signal()
    fieldActionRequested = Signal(object, str)
    editorApplyRequested = Signal(object, object, object)
    editorClosed = Signal()

    def __init__(self, locale_getter, parent=None):
        super().__init__(parent)
        self.locale_getter = locale_getter
        self.report: FileReport | None = None
        self.display_path: Path | None = None
        self.field_states: dict[str, str] = {}
        self.current_filter = "important"
        self.selected_field: MetaField | None = None
        self._last_sensitive_count: int = 0
        self._save_button_base = (
            f"QPushButton {{ background:{COLORS['success']}; border-color:{COLORS['success']}; "
            "color: #f8fafc; padding: 0 16px; }}"
        )
        self._save_button_modified = (
            "QPushButton { background:#16a34a; border-color:#22c55e; color: #f8fafc; padding: 0 16px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.left_card = GlassCard(self)
        self.left_card.setFixedWidth(220)
        left_layout = QVBoxLayout(self.left_card)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        self.preview_label = QLabel(self.left_card)
        self.preview_label.setFixedSize(160, 120)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFont(QFont("Segoe UI", 12, QFont.Medium))
        self.preview_label.setStyleSheet(
            "background: rgba(255,255,255,0.04); border-radius: 10px; color: #f8fafc;"
        )
        left_layout.addWidget(self.preview_label, alignment=Qt.AlignCenter)

        self.file_name = QLabel(self.left_card)
        self.file_name.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.file_name.setWordWrap(False)
        left_layout.addWidget(self.file_name)

        self.file_size = QLabel(self.left_card)
        self.file_size.setFont(QFont("Segoe UI", 10))
        self.file_size.setStyleSheet("color:#94a3b8;")
        self.file_size.setWordWrap(False)
        left_layout.addWidget(self.file_size)

        self.file_badge_host = QHBoxLayout()
        left_layout.addLayout(self.file_badge_host)

        divider = QFrame(self.left_card)
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: rgba(255,255,255,0.08);")
        left_layout.addWidget(divider)

        self.risk_widget = RiskWidget(self.left_card)
        left_layout.addWidget(self.risk_widget, alignment=Qt.AlignCenter)

        self.risk_label = QLabel(self.left_card)
        self.risk_label.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
        self.risk_label.setWordWrap(False)
        left_layout.addWidget(self.risk_label, alignment=Qt.AlignCenter)
        left_layout.addStretch(1)

        self.center_card = GlassCard(self)
        center_layout = QVBoxLayout(self.center_card)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)

        filter_row = QHBoxLayout()
        self.important_button = QPushButton(self.center_card)
        self.important_button.setCheckable(True)
        self.important_button.setMinimumWidth(100)
        self.important_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.important_button.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.important_button.setStyleSheet("QPushButton { padding: 6px 12px; }")
        self.important_button.clicked.connect(lambda: self.set_filter_mode("important"))
        filter_row.addWidget(self.important_button)

        self.all_button = QPushButton(self.center_card)
        self.all_button.setCheckable(True)
        self.all_button.setMinimumWidth(100)
        self.all_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.all_button.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.all_button.setStyleSheet("QPushButton { padding: 6px 12px; }")
        self.all_button.clicked.connect(lambda: self.set_filter_mode("all"))
        filter_row.addWidget(self.all_button)
        filter_row.addStretch(1)
        center_layout.addLayout(filter_row)

        self.table = MetaTable(self.locale_getter, self.center_card)
        self.table.fieldActionRequested.connect(self.fieldActionRequested)
        center_layout.addWidget(self.table, 1)

        self.overlay = QFrame(self.center_card)
        self.overlay.setStyleSheet(
            "background: rgba(0,0,0,0.45); border-radius: 16px; color: #f8fafc;"
        )
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(24, 24, 24, 24)
        overlay_layout.addStretch(1)
        self.overlay_label = QLabel(self.overlay)
        self.overlay_label.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setWordWrap(True)
        overlay_layout.addWidget(self.overlay_label)
        self.overlay_progress = QProgressBar(self.overlay)
        self.overlay_progress.setRange(0, 0)
        overlay_layout.addWidget(self.overlay_progress)
        overlay_layout.addStretch(1)
        self.overlay.hide()

        self.side_panel = AnimatedSidePanel(self)
        self.editor = SpoofEditor(self.locale_getter, self.side_panel)
        self.editor.applyRequested.connect(self.editorApplyRequested)
        self.editor.closeRequested.connect(self.editorClosed)
        self.side_panel.layout.addWidget(self.editor)

        self.splitter.addWidget(self.left_card)
        self.splitter.addWidget(self.center_card)
        self.splitter.addWidget(self.side_panel)
        self.splitter.setSizes([220, 700, 0])

        self.status_label = QLabel(self)
        self.status_label.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.status_label.setStyleSheet("color:#94a3b8; padding: 0 4px;")
        self.status_label.setWordWrap(False)
        root.addWidget(self.status_label)

        self.footer = GlassCard(self)
        self.footer.setMinimumHeight(56)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.addStretch(1)

        self.clean_residual_button = QPushButton(self.footer)
        self.clean_residual_button.setMinimumHeight(36)
        self.clean_residual_button.setMinimumWidth(130)
        self.clean_residual_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.clean_residual_button.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.clean_residual_button.setStyleSheet(
            "QPushButton { background: rgba(245,158,11,0.18); border-color:#f59e0b; color: #f8fafc; padding: 0 16px; }"
        )
        self.clean_residual_button.clicked.connect(self.cleanResidualRequested)
        self.clean_residual_button.hide()
        footer_layout.addWidget(self.clean_residual_button)

        self.remove_button = QPushButton(self.footer)
        self.remove_button.setMinimumHeight(36)
        self.remove_button.setMinimumWidth(130)
        self.remove_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.remove_button.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.remove_button.setStyleSheet(
            "QPushButton { background: rgba(239,68,68,0.15); border-color:#ef4444; color: #f8fafc; padding: 0 16px; }"
        )
        self.remove_button.clicked.connect(self.removeAllRequested)
        footer_layout.addWidget(self.remove_button)

        self.smart_button = QPushButton(self.footer)
        self.smart_button.setMinimumHeight(36)
        self.smart_button.setMinimumWidth(130)
        self.smart_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.smart_button.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.smart_button.setStyleSheet(
            f"QPushButton {{ background:{COLORS['accent']}; border-color:{COLORS['accent']}; "
            "color: #f8fafc; padding: 0 16px; }}"
        )
        self.smart_button.clicked.connect(self.smartSpoofRequested)
        footer_layout.addWidget(self.smart_button)

        self.save_button = QPushButton(self.footer)
        self.save_button.setMinimumHeight(36)
        self.save_button.setMinimumWidth(130)
        self.save_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.save_button.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.save_button.setStyleSheet(self._save_button_base)
        self.save_button.clicked.connect(self.saveRequested)
        footer_layout.addWidget(self.save_button)
        root.addWidget(self.footer)

        self.refresh_locale()

    def resizeEvent(self, event) -> None:  # pragma: no cover - layout only
        super().resizeEvent(event)
        self.overlay.setGeometry(self.center_card.rect())

    def locale(self) -> str:
        return self.locale_getter()

    def set_filter_mode(self, mode: str) -> None:
        self.current_filter = mode
        # Avoid refresh_locale(): it hits the filesystem and rebuilds the table before the filter applies.
        self.important_button.setChecked(mode == "important")
        self.all_button.setChecked(mode == "all")
        locale = self.locale()
        important_count = 0 if self.report is None else sum(1 for f in self.report.fields if f.is_sensitive)
        all_count = 0 if self.report is None else len(self.report.fields)
        self.important_button.setText(f"{tr(locale, 'important')} ({important_count})")
        self.all_button.setText(f"{tr(locale, 'all')} ({all_count})")
        self._reload_table()

    def set_report(
        self,
        report: FileReport,
        field_states: dict[str, str],
        selected_field: MetaField | None = None,
        display_path: Path | None = None,
    ) -> None:
        self.report = report
        self.display_path = display_path or report.path
        self.field_states = dict(field_states)
        self.selected_field = selected_field
        self._update_file_info()
        self._reload_table()
        if selected_field is not None:
            self.open_editor(selected_field)
        else:
            self.close_editor()

    def open_editor(self, field: MetaField) -> None:
        if self.report is None:
            return
        self.selected_field = field
        try:
            self.editor.set_context(self.report, field)
        except Exception:
            pass  # malformed values: open empty panel so user can close it
        self.side_panel.reveal(True)

    def close_editor(self) -> None:
        self.selected_field = None
        self.side_panel.reveal(False)

    def set_busy(self, busy: bool, message: str | None = None) -> None:
        self.overlay_label.setText(message or tr(self.locale(), "loading"))
        self.overlay.setVisible(busy)
        for button in (self.clean_residual_button, self.remove_button, self.smart_button, self.save_button):
            button.setDisabled(busy)

    def set_status_message(self, message: str) -> None:
        self.status_label.setText(message)

    def set_clean_residual_visible(self, visible: bool) -> None:
        self.clean_residual_button.setVisible(visible)

    def set_modified_state(self, modified: bool) -> None:
        self.save_button.setStyleSheet(self._save_button_modified if modified else self._save_button_base)

    def refresh_locale(self) -> None:
        locale = self.locale()
        important_count = 0 if self.report is None else sum(1 for field in self.report.fields if field.is_sensitive)
        all_count = 0 if self.report is None else len(self.report.fields)
        self.important_button.setText(f"{tr(locale, 'important')} ({important_count})")
        self.all_button.setText(f"{tr(locale, 'all')} ({all_count})")
        self.important_button.setChecked(self.current_filter == "important")
        self.all_button.setChecked(self.current_filter == "all")
        self.clean_residual_button.setText(tr(locale, "clean_residual_btn"))
        self.remove_button.setText(tr(locale, "remove_all"))
        self.smart_button.setText(tr(locale, "smart_spoof"))
        self.save_button.setText(tr(locale, "save_copy"))
        self.overlay_label.setText(tr(locale, "loading"))
        self.table.refresh_locale()
        self.editor.refresh_locale()
        if self.report is not None:
            # Skip _update_file_info(): locale change shouldn't touch disk; OSError would skip _reload_table().
            self._refresh_risk_label()
            self._reload_table()

    def _clear_layout(self, layout: QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _refresh_risk_label(self) -> None:
        risk_text, color = risk_state(self._last_sensitive_count, self.locale())
        self.risk_widget.set_state(self._last_sensitive_count, color)
        self.risk_label.setText(risk_text)
        self.risk_label.setStyleSheet(f"color:{color};")

    def _update_file_info(self) -> None:
        if self.report is None:
            return
        metrics = QFontMetrics(self.file_name.font())
        display_path = self.display_path or self.report.path
        self.file_name.setText(metrics.elidedText(display_path.name, Qt.ElideRight, 180))
        try:
            self.file_size.setText(f"{Path(display_path).stat().st_size} bytes")
        except OSError:
            pass
        self._clear_layout(self.file_badge_host)
        self.file_badge_host.addWidget(TagBadge.for_format(self.report.file_type, self.left_card))
        self.file_badge_host.addStretch(1)

        if self.report.thumbnail:
            image = Image.open(io.BytesIO(self.report.thumbnail))
            image.thumbnail((160, 120))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            self.preview_label.setPixmap(pixmap)
            self.preview_label.setText("")
        else:
            self.preview_label.setPixmap(QPixmap())
            if self.report.file_type == "raw":
                self.preview_label.setText("📷 RAW")
            elif self.report.file_type in {"jpeg", "png", "heic", "heif", "tiff", "webp"}:
                self.preview_label.setText("🖼 IMAGE")
            else:
                self.preview_label.setText(self.report.file_type.upper())

        self._last_sensitive_count = sum(1 for field in self.report.fields if field.status == "risk")
        self._refresh_risk_label()

    def _reload_table(self) -> None:
        if self.report is None:
            return
        self.table.set_report(self.report, self.field_states, self.current_filter)
