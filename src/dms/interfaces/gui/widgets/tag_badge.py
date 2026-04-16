"""Badge-style labels used across the GUI."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel

from dms.interfaces.gui.theme import FILE_BADGE_COLORS, status_colors


class TagBadge(QLabel):
    """Small pill-like badge with colored border and background."""

    def __init__(self, text: str, background: str, border: str, foreground: str, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self.setStyleSheet(
            f"""
            QLabel {{
                background: {background};
                border: 1px solid {border};
                border-radius: 4px;
                color: {foreground};
                padding: 2px 6px;
            }}
            """
        )

    @classmethod
    def for_status(cls, status: str, parent=None) -> "TagBadge":
        bg, border, fg = status_colors(status)
        return cls(status, bg, border, fg, parent)

    @classmethod
    def for_format(cls, file_type: str, parent=None) -> "TagBadge":
        color = FILE_BADGE_COLORS.get(file_type, "#6366f1")
        return cls(file_type.upper(), f"{color}33", color, "#f8fafc", parent)
