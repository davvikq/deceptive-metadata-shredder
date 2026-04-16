"""Transient toast notifications."""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QWidget

from dms.interfaces.gui.theme import COLORS


class Toast(QWidget):
    """Fading toast; opacity animation only (no geometry flicker)."""

    TOAST_COLORS = {
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "danger": COLORS["danger"],
        "info": COLORS["accent"],
    }
    TOAST_ICONS = {
        "success": "\u2713",
        "warning": "\u26A0",
        "danger": "\u2717",
        "info": "i",
    }

    dismissed = Signal(object)

    def __init__(self, message: str = "", kind: str = "success", parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self._message = message
        self._fade_in: QPropertyAnimation | None = None
        self._fade_out: QPropertyAnimation | None = None

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedWidth(320)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 153))
        self.setGraphicsEffect(shadow)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stripe = QFrame(self)
        self.stripe.setFixedWidth(4)
        root.addWidget(self.stripe)

        content = QWidget(self)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(14, 14, 18, 14)
        content_layout.setSpacing(12)

        self.icon_label = QLabel(content)
        self.icon_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        content_layout.addWidget(self.icon_label)

        self.label = QLabel(content)
        self.label.setFont(QFont("Segoe UI", 13, QFont.Medium))
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color:#f8fafc;")
        content_layout.addWidget(self.label, 1)
        root.addWidget(content, 1)

        self._apply_kind(kind)
        if message:
            self.label.setText(message)

    def _apply_kind(self, kind: str) -> None:
        color = self.TOAST_COLORS.get(kind, COLORS["accent"])
        self.stripe.setStyleSheet(f"background:{color}; border-radius: 2px; color: #f8fafc;")
        self.icon_label.setText(self.TOAST_ICONS.get(kind, "i"))
        self.icon_label.setStyleSheet(f"color:{color};")

    def paintEvent(self, _event) -> None:  # pragma: no cover - UI paint code
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, QColor(15, 15, 30, 247))
        pen = QPen(QColor(255, 255, 255, 31))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)

    def show_message(self, message: str | None = None, kind: str | None = None, position=None) -> None:
        if message is not None:
            self._message = message
        if kind is not None:
            self.kind = kind
        self._apply_kind(self.kind)
        self.label.setText(self._message)
        self.setWindowOpacity(0.0)
        self.show()
        self.adjustSize()
        if position is not None:
            self.move(position)
        self.raise_()

        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.start()
        QTimer.singleShot(3000, self._fade_out_message)

    def reposition(self, position) -> None:
        self.move(position)

    def _fade_out_message(self) -> None:
        self._fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self._finalize_close)
        self._fade_out.start()

    def _finalize_close(self) -> None:
        self.dismissed.emit(self)
        self.hide()
        self.close()
