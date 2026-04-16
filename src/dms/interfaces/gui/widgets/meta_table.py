"""Metadata table widget built on QTreeWidget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from dms.core.constants import ALWAYS_DELETE_PREFIXES
from dms.core.models import FileReport, MetaField
from dms.interfaces.gui.theme import GROUP_META, tr
from dms.interfaces.gui.widgets.tag_badge import TagBadge

# OS-managed timestamp fields: they cannot be deleted, only overwritten.
_SYSTEM_DATE_KEYS: frozenset[str] = frozenset({"FileModifyDate", "FileAccessDate", "FileCreateDate"})


def _is_region_field(field: MetaField) -> bool:
    normalized = field.key.split(":")[-1].split(".")[-1]
    return any(normalized.startswith(p) for p in ALWAYS_DELETE_PREFIXES)


class MetaTable(QTreeWidget):
    """Collapsible metadata tree with action buttons."""

    fieldActionRequested = Signal(object, str)

    def __init__(self, locale_getter, parent=None):
        super().__init__(parent)
        self.locale_getter = locale_getter
        self.report: FileReport | None = None
        self.field_states: dict[str, str] = {}
        self.filter_mode = "important"
        self._action_font = QFont("Segoe UI", 11, QFont.Medium)

        self.setColumnCount(4)
        self.setHeaderLabels(["Tag", "Value", "Status", "Actions"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setIndentation(16)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self.header().setSectionResizeMode(3, QHeaderView.Fixed)
        self.setColumnWidth(2, 90)
        self.setColumnWidth(3, 72)

    def set_report(self, report: FileReport, field_states: dict[str, str], filter_mode: str) -> None:
        """Reload the table from a fresh FileReport."""

        self.report = report
        self.field_states = field_states
        self.filter_mode = filter_mode
        self._populate()

    def refresh_locale(self) -> None:
        """Repaint text using the current locale."""

        self.setHeaderLabels(["Tag", "Value", "Status", "Actions"])
        if self.report is not None:
            self._populate()

    def _locale(self) -> str:
        return self.locale_getter()

    def _visible_fields(self) -> list[MetaField]:
        if self.report is None:
            return []
        if self.filter_mode == "important":
            return [field for field in self.report.fields if field.is_sensitive]
        return list(self.report.fields)

    def _grouped(self) -> list[tuple[str, list[MetaField]]]:
        groups = {"gps": [], "device": [], "author_dates": [], "other": []}
        for field in self._visible_fields():
            if field.category == "gps":
                groups["gps"].append(field)
            elif field.category == "device":
                groups["device"].append(field)
            elif field.category in {"author", "dates"}:
                groups["author_dates"].append(field)
            else:
                groups["other"].append(field)
        return [(key, items) for key, items in groups.items() if items]

    def _status(self, field: MetaField) -> str:
        if getattr(field, "status", "") == "spoofed":
            return "SPOOFED"
        if getattr(field, "status", "") in {"removed", "clean"}:
            return "CLEAN"
        state = self.field_states.get(field.key)
        if state == "spoofed":
            return "SPOOFED"
        if state == "removed" or not field.is_sensitive:
            return "CLEAN"
        return "RISK"

    def _populate(self) -> None:
        self.setUpdatesEnabled(False)
        self.clear()
        locale = self._locale()
        for group_key, fields in self._grouped():
            icon, title_key = GROUP_META[group_key]
            parent = QTreeWidgetItem([f"{icon} {tr(locale, title_key)} ({len(fields)})", "", "", ""])
            parent.setFirstColumnSpanned(True)
            parent.setExpanded(True)
            parent.setFlags(Qt.ItemIsEnabled)
            self.addTopLevelItem(parent)
            for field in fields:
                value = "" if field.value is None else str(field.value)
                item = QTreeWidgetItem(parent, [field.label, value, "", ""])
                item.setData(0, Qt.UserRole, field)
                item.setToolTip(1, field.exiftool_tag)
                if field.is_computed:
                    tip_key = "region_tooltip" if _is_region_field(field) else "computed_tooltip"
                    item.setToolTip(3, tr(locale, tip_key))
                self.setItemWidget(item, 2, TagBadge.for_status(self._status(field), self))
                self.setItemWidget(item, 3, self._action_widget(field))
        self.expandAll()
        self.setUpdatesEnabled(True)

    def _action_widget(self, field: MetaField) -> QWidget:
        host = QWidget(self)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(4, 2, 8, 2)
        layout.setSpacing(6)

        if field.is_computed:
            info = QLabel("\u2139", host)
            info.setFont(self._action_font)
            info.setStyleSheet("color:#94a3b8;")
            tip_key = "region_tooltip" if _is_region_field(field) else "computed_tooltip"
            info.setToolTip(tr(self._locale(), tip_key))
            layout.addWidget(info)
            layout.addStretch(1)
            return host

        if field.key in _SYSTEM_DATE_KEYS:
            # System timestamp: cannot be deleted.
            # 🎲 = quick random past date; ... = open full date editor for custom input.
            dice_button = QPushButton("\U0001f3b2", host)
            dice_button.setFont(self._action_font)
            dice_button.setFixedSize(28, 28)
            dice_button.setStyleSheet(
                "QPushButton { padding:0; border-radius:6px; background: rgba(99,102,241,0.0); color:#94a3b8; border:none; }"
                "QPushButton:hover { background: rgba(99,102,241,0.2); color:#a5b4fc; }"
                "QPushButton:pressed { background: rgba(99,102,241,0.35); color:#a5b4fc; }"
            )
            dice_button.setToolTip(tr(self._locale(), "system_date_tooltip"))
            dice_button.clicked.connect(lambda: self.fieldActionRequested.emit(field, "randomize_fs_date"))
            layout.addWidget(dice_button)

            edit_button = QPushButton("...", host)
            edit_button.setFont(self._action_font)
            edit_button.setFixedSize(28, 28)
            edit_button.setStyleSheet(
                "QPushButton { padding:0; border-radius:6px; background: rgba(99,102,241,0.0); color:#94a3b8; border:none; }"
                "QPushButton:hover { background: rgba(99,102,241,0.2); color:#a5b4fc; }"
                "QPushButton:pressed { background: rgba(99,102,241,0.35); color:#a5b4fc; }"
            )
            edit_button.setToolTip(tr(self._locale(), "system_date_tooltip"))
            edit_button.clicked.connect(lambda: self.fieldActionRequested.emit(field, "spoof"))
            layout.addWidget(edit_button)

            layout.addStretch(1)
            return host

        remove_button = QPushButton("X", host)
        remove_button.setFont(self._action_font)
        remove_button.setFixedSize(28, 28)
        remove_button.setStyleSheet(
            "QPushButton { padding:0; border-radius:6px; background: rgba(239,68,68,0.0); color:#94a3b8; border:none; }"
            "QPushButton:hover { background: rgba(239,68,68,0.2); color:#ef4444; }"
            "QPushButton:pressed { background: rgba(239,68,68,0.35); color:#ef4444; }"
        )
        remove_button.clicked.connect(lambda: self.fieldActionRequested.emit(field, "remove"))
        layout.addWidget(remove_button)

        spoof_button = QPushButton("...", host)
        spoof_button.setFont(self._action_font)
        spoof_button.setFixedSize(28, 28)
        spoof_button.setStyleSheet(
            "QPushButton { padding:0; border-radius:6px; background: rgba(99,102,241,0.0); color:#94a3b8; border:none; }"
            "QPushButton:hover { background: rgba(99,102,241,0.2); color:#a5b4fc; }"
            "QPushButton:pressed { background: rgba(99,102,241,0.35); color:#a5b4fc; }"
        )
        spoof_button.clicked.connect(lambda: self.fieldActionRequested.emit(field, "spoof"))
        layout.addWidget(spoof_button)

        layout.addStretch(1)
        return host
