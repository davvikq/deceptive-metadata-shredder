"""Reusable translucent card container."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsBlurEffect


class GlassCard(QFrame):
    """Rounded frosted panel (custom paint)."""

    def __init__(self, parent=None, radius: int = 16):
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self.radius = radius
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFrameShape(QFrame.NoFrame)
        blur = QGraphicsBlurEffect(self)
        blur.setBlurRadius(20)
        blur.setEnabled(False)
        self._blur = blur

    def paintEvent(self, _event) -> None:  # pragma: no cover - UI paint code
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)

        painter.fillPath(path, QColor(255, 255, 255, 13))

        overlay = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.top() + rect.height() * 0.35))
        overlay.setColorAt(0.0, QColor(255, 255, 255, 20))
        overlay.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, overlay)

        pen = QPen(QColor(255, 255, 255, 25))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
