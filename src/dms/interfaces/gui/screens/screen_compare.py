"""Before/after comparison screen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dms.core.models import FileReport, MetaField
from dms.interfaces.gui.theme import COLORS, tr
from dms.interfaces.gui.widgets.glass_card import GlassCard


@dataclass(slots=True)
class DiffRow:
    key: str
    label: str
    orig_value: object | None
    clean_value: object | None
    category: str
    status: str


def compute_diff(original: FileReport, cleaned: FileReport) -> list[DiffRow]:
    orig_dict = {field.key: field for field in original.fields}
    clean_dict = {field.key: field for field in cleaned.fields}
    all_keys = sorted(set(orig_dict) | set(clean_dict))

    rows: list[DiffRow] = []
    for key in all_keys:
        orig_field = orig_dict.get(key)
        clean_field = clean_dict.get(key)
        if orig_field and clean_field:
            status = "unchanged" if str(orig_field.value) == str(clean_field.value) else "changed"
        elif orig_field and not clean_field:
            status = "removed"
        else:
            status = "added"
        rows.append(
            DiffRow(
                key=key,
                label=(orig_field or clean_field).label,  # type: ignore[union-attr]
                orig_value=orig_field.value if orig_field else None,
                clean_value=clean_field.value if clean_field else None,
                category=(orig_field or clean_field).category,  # type: ignore[union-attr]
                status=status,
            )
        )
    return rows


def _category_title(category: str) -> str:
    return {
        "gps": "📍 GPS & Location",
        "device": "📷 Device",
        "author": "👤 Author",
        "dates": "📅 Dates",
        "other": "🔧 Other",
    }.get(category, category.title())


def _value_text(value: object | None, fallback: str) -> str:
    if value in (None, ""):
        return fallback
    return str(value)


class ScreenCompare(QWidget):
    """Side-by-side original vs edited metadata."""

    backRequested = Signal()
    saveRequested = Signal()

    def __init__(self, locale_getter, parent=None):
        super().__init__(parent)
        self.locale_getter = locale_getter
        self.original: FileReport | None = None
        self.cleaned: FileReport | None = None
        self.rows: list[DiffRow] = []
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.toggle_unchanged = QCheckBox(self)
        self.toggle_unchanged.toggled.connect(self._rebuild)
        root.addWidget(self.toggle_unchanged, alignment=Qt.AlignLeft)

        self.splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(self.splitter, 1)

        self.left_scroll = QScrollArea(self)
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_container = QWidget(self.left_scroll)
        self.left_layout = QVBoxLayout(self.left_container)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(4)
        self.left_scroll.setWidget(self.left_container)

        self.middle = QWidget(self)
        self.middle.setFixedWidth(40)
        self.middle_layout = QVBoxLayout(self.middle)
        self.middle_layout.setContentsMargins(0, 0, 0, 0)
        self.middle_layout.setSpacing(4)

        self.right_scroll = QScrollArea(self)
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_container = QWidget(self.right_scroll)
        self.right_layout = QVBoxLayout(self.right_container)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(4)
        self.right_scroll.setWidget(self.right_container)

        self.splitter.addWidget(self.left_scroll)
        self.splitter.addWidget(self.middle)
        self.splitter.addWidget(self.right_scroll)
        self.splitter.setSizes([520, 40, 520])

        self.left_scroll.verticalScrollBar().valueChanged.connect(lambda value: self._sync_scroll("left", value))
        self.right_scroll.verticalScrollBar().valueChanged.connect(lambda value: self._sync_scroll("right", value))

        self.summary_card = GlassCard(self)
        summary_layout = QHBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        self.summary_left = QLabel(self.summary_card)
        self.summary_center = QLabel(self.summary_card)
        self.summary_right = QLabel(self.summary_card)
        for label in (self.summary_left, self.summary_center, self.summary_right):
            label.setFont(QFont("Segoe UI", 10, QFont.Medium))
        summary_layout.addWidget(self.summary_left)
        summary_layout.addStretch(1)
        summary_layout.addWidget(self.summary_center)
        summary_layout.addStretch(1)
        summary_layout.addWidget(self.summary_right)
        root.addWidget(self.summary_card)

        footer = QHBoxLayout()
        self.back_button = QPushButton(self)
        self.back_button.clicked.connect(self.backRequested)
        footer.addWidget(self.back_button)
        footer.addStretch(1)
        self.save_button = QPushButton(self)
        self.save_button.setStyleSheet(
            f"QPushButton {{ background:{COLORS['success']}; border-color:{COLORS['success']}; color: #f8fafc; }}"
        )
        self.save_button.clicked.connect(self.saveRequested)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self.refresh_locale()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _sync_scroll(self, source: str, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            target = self.right_scroll if source == "left" else self.left_scroll
            target.verticalScrollBar().setValue(value)
        finally:
            self._syncing = False

    def refresh_locale(self) -> None:
        locale = self.locale_getter()
        unchanged = sum(1 for row in self.rows if row.status == "unchanged")
        key = "compare_show_unchanged" if not self.toggle_unchanged.isChecked() else "compare_hide_unchanged"
        self.toggle_unchanged.setText(tr(locale, key, n=unchanged))
        self.back_button.setText(tr(locale, "compare_back"))
        self.save_button.setText(tr(locale, "compare_save"))
        if self.original and self.cleaned:
            self._update_summary()

    def set_reports(self, original: FileReport, cleaned: FileReport) -> None:
        self.original = original
        self.cleaned = cleaned
        self.rows = compute_diff(original, cleaned)
        self.refresh_locale()
        self._rebuild()

    def _grouped_rows(self) -> dict[str, list[DiffRow]]:
        grouped: dict[str, list[DiffRow]] = {}
        for row in self.rows:
            if row.status == "unchanged" and not self.toggle_unchanged.isChecked():
                continue
            grouped.setdefault(row.category, []).append(row)
        return grouped

    def _row_widget(self, row: DiffRow, side: str) -> QWidget:
        locale = self.locale_getter()
        widget = QWidget(self)
        widget.setMinimumHeight(36)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        tag = QLabel(row.label, widget)
        tag.setFixedWidth(160)
        tag.setFont(QFont("Segoe UI", 10))
        tag.setStyleSheet(f"color:{COLORS['text_secondary']};")
        layout.addWidget(tag)

        value = QLabel(widget)
        value.setFont(QFont("Cascadia Code", 10))
        value.setWordWrap(False)
        layout.addWidget(value, 1)
        badge: QLabel | None = None

        if row.status == "unchanged":
            value.setText(_value_text(row.orig_value if side == "left" else row.clean_value, "—"))
            value.setStyleSheet(f"color:{COLORS['text_secondary']};")
        elif row.status == "changed":
            if side == "left":
                value.setText(_value_text(row.orig_value, "—"))
                value.setStyleSheet(f"color:{COLORS['danger']}; text-decoration: line-through; background: rgba(239,68,68,0.08);")
            else:
                value.setText(_value_text(row.clean_value, "—"))
                value.setStyleSheet(f"color:{COLORS['success']}; background: rgba(34,197,94,0.08);")
        elif row.status == "removed":
            if side == "left":
                value.setText(_value_text(row.orig_value, "—"))
                value.setStyleSheet(f"color:{COLORS['danger']}; text-decoration: line-through; background: rgba(239,68,68,0.08);")
            else:
                value.setText(tr(locale, "compare_removed"))
                value.setStyleSheet("color:#475569; font-style: italic;")
        else:
            if side == "left":
                value.setText(tr(locale, "compare_not_present"))
                value.setStyleSheet("color:#475569; font-style: italic;")
            else:
                value.setText(_value_text(row.clean_value, "—"))
                value.setStyleSheet(f"color:{COLORS['success']}; background: rgba(34,197,94,0.08);")

        if row.status == "added":
            if side == "left":
                value.setText(tr(locale, "compare_injected"))
                value.setStyleSheet(f"color:{COLORS['danger']}; font-style: italic;")
            else:
                value.setStyleSheet(f"color:{COLORS['danger']}; background: rgba(239,68,68,0.08);")
                badge = QLabel(tr(locale, "compare_injected_badge"), widget)
                badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
                badge.setStyleSheet(
                    f"color:{COLORS['danger']};"
                    "background: rgba(239,68,68,0.18);"
                    f"border: 1px solid {COLORS['danger']};"
                    "border-radius: 4px; padding: 2px 6px;"
                )
                layout.addWidget(badge)
        return widget

    def _middle_widget(self, row: DiffRow) -> QWidget:
        widget = QWidget(self)
        widget.setMinimumHeight(36)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 4)
        arrow = QLabel("→" if row.status == "changed" else "", widget)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setStyleSheet(f"color:{COLORS['accent']};")
        if row.status in {"changed", "added"}:
            arrow.setText("->")
        if row.status == "added":
            arrow.setStyleSheet(f"color:{COLORS['danger']};")
        layout.addWidget(arrow)
        return widget

    def _section_header(self, title: str) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 4)
        label = QLabel(title, widget)
        label.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        label.setStyleSheet(f"color:{COLORS['text_secondary']};")
        line = QFrame(widget)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(255,255,255,0.08);")
        layout.addWidget(label)
        layout.addWidget(line)
        return widget

    def _rebuild(self) -> None:
        self._clear_layout(self.left_layout)
        self._clear_layout(self.middle_layout)
        self._clear_layout(self.right_layout)

        locale = self.locale_getter()
        left_title = QLabel(tr(locale, "compare_original"), self.left_container)
        left_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        left_title.setStyleSheet(f"color:{COLORS['text_secondary']};")
        self.left_layout.addWidget(left_title)
        right_title = QLabel(tr(locale, "compare_cleaned"), self.right_container)
        right_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        right_title.setStyleSheet(f"color:{COLORS['text_secondary']};")
        self.right_layout.addWidget(right_title)
        self.middle_layout.addWidget(QWidget(self.middle))

        for category, rows in self._grouped_rows().items():
            self.left_layout.addWidget(self._section_header(_category_title(category)))
            self.right_layout.addWidget(self._section_header(_category_title(category)))
            self.middle_layout.addWidget(QWidget(self.middle))
            for row in rows:
                self.left_layout.addWidget(self._row_widget(row, "left"))
                self.middle_layout.addWidget(self._middle_widget(row))
                self.right_layout.addWidget(self._row_widget(row, "right"))

        self.left_layout.addStretch(1)
        self.middle_layout.addStretch(1)
        self.right_layout.addStretch(1)
        self._update_summary()

    def _update_summary(self) -> None:
        if not self.original or not self.cleaned:
            return
        locale = self.locale_getter()
        orig_count = sum(1 for field in self.original.fields if field.is_sensitive)
        clean_count = sum(1 for field in self.cleaned.fields if getattr(field, "status", "risk") == "risk")
        removed = sum(1 for row in self.rows if row.status == "removed")
        changed = sum(1 for row in self.rows if row.status == "changed")
        unchanged = sum(1 for row in self.rows if row.status == "unchanged")
        self.summary_left.setText(f"⚠ {orig_count} sensitive fields")
        self.summary_left.setStyleSheet(f"color:{COLORS['danger']};")
        self.summary_center.setText(tr(locale, "compare_summary", r=removed, s=changed, u=unchanged))
        self.summary_center.setStyleSheet(f"color:{COLORS['text_secondary']};")
        if clean_count == 0:
            self.summary_right.setText("✓ Clean")
            self.summary_right.setStyleSheet(f"color:{COLORS['success']};")
        else:
            self.summary_right.setText(f"⚠ {clean_count} remaining")
            self.summary_right.setStyleSheet(f"color:{COLORS['warning']};")
