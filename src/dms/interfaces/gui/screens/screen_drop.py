"""Initial drag-and-drop screen."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from dms.interfaces.gui.theme import tr
from dms.interfaces.gui.widgets.glass_card import GlassCard


def _fit_label_font(label: QLabel, text: str, max_width: int, sizes: tuple[int, ...] = (14, 13, 12, 11, 10)) -> None:
    face = label.font().family() or "Segoe UI"
    weight = label.font().weight()
    for size in sizes:
        font = QFont(face, size, weight)
        if QFontMetrics(font).horizontalAdvance(text) <= max_width:
            label.setFont(font)
            return
    label.setFont(QFont(face, sizes[-1], weight))

SHIELD_SVG = b"""
<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6l7-3z"/>
  <path d="M8 12a4 4 0 0 1 8 0"/>
  <path d="M7 17l10-10"/>
</svg>
"""


def _shield_pixmap() -> QPixmap:
    pixmap = QPixmap(80, 80)
    pixmap.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(SHIELD_SVG))
    painter = None
    from PySide6.QtGui import QPainter

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


class DropZoneCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(400, 220)
        self.active = False

    def set_drag_active(self, active: bool) -> None:
        self.active = active
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - UI paint code
        super().paintEvent(event)
        from PySide6.QtGui import QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#6366f1" if self.active else "#ffffff33"))
        pen.setWidth(2)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect().adjusted(8, 8, -8, -8), 18, 18)


class ScreenDrop(QWidget):
    """Landing screen with drop zone and browse."""

    browseRequested = Signal()

    def __init__(self, locale_getter, parent=None):
        super().__init__(parent)
        self.locale_getter = locale_getter

        root = QVBoxLayout(self)
        root.addStretch(1)

        center = QVBoxLayout()
        center.setAlignment(Qt.AlignHCenter)
        center.setSpacing(12)
        root.addLayout(center)

        self.icon_label = QLabel(self)
        self.icon_label.setPixmap(_shield_pixmap())
        self.icon_label.setAlignment(Qt.AlignCenter)
        center.addWidget(self.icon_label)

        self.title_label = QLabel(self)
        self.title_label.setFont(QFont("Segoe UI", 24, QFont.Bold))
        self.title_label.setStyleSheet("color:#f8fafc;")
        center.addWidget(self.title_label, alignment=Qt.AlignCenter)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setFont(QFont("Segoe UI", 14))
        self.subtitle_label.setStyleSheet("color:#94a3b8;")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setMaximumWidth(420)
        center.addWidget(self.subtitle_label, alignment=Qt.AlignCenter)

        self.drop_card = DropZoneCard(self)
        card_layout = QVBoxLayout(self.drop_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        card_layout.addStretch(1)
        self.drop_label = QLabel(self.drop_card)
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setFont(QFont("Segoe UI", 14, QFont.DemiBold))
        self.drop_label.setStyleSheet("color:#f8fafc;")
        self.drop_label.setWordWrap(True)
        self.drop_label.setMaximumWidth(360)
        card_layout.addWidget(self.drop_label)
        self.formats_label = QLabel(self.drop_card)
        self.formats_label.setAlignment(Qt.AlignCenter)
        self.formats_label.setFont(QFont("Segoe UI", 12))
        self.formats_label.setStyleSheet("color:#94a3b8;")
        self.formats_label.setToolTip("CR2, CR3, NEF, ARW, DNG, RAF and more")
        card_layout.addWidget(self.formats_label)
        card_layout.addStretch(1)
        center.addWidget(self.drop_card, alignment=Qt.AlignCenter)

        self.browse_button = QPushButton(self)
        self.browse_button.setFont(QFont("Segoe UI", 11, QFont.Medium))
        self.browse_button.setStyleSheet(
            "QPushButton { background:#6366f1; border-color:#6366f1; color: #f8fafc; padding:10px 20px; font-weight:600; }"
            "QPushButton:hover { background:#4f46e5; color: #f8fafc; }"
        )
        self.browse_button.clicked.connect(self.browseRequested)
        center.addWidget(self.browse_button, alignment=Qt.AlignCenter)

        root.addStretch(2)
        self.refresh_locale()

    def refresh_locale(self) -> None:
        locale = self.locale_getter()
        self.title_label.setText(tr(locale, "full_title"))

        subtitle_text = tr(locale, "drop_subtitle")
        self.subtitle_label.setText(subtitle_text)
        _fit_label_font(self.subtitle_label, subtitle_text, 400, (14, 13, 12, 11, 10))

        drop_text = tr(locale, "drop_subtitle")
        self.drop_label.setText(drop_text)
        _fit_label_font(self.drop_label, drop_text, 340, (14, 13, 12, 11, 10))

        self.formats_label.setText(tr(locale, "drop_formats"))
        self.browse_button.setText(tr(locale, "browse_file"))

    def set_drag_active(self, active: bool) -> None:
        self.drop_card.set_drag_active(active)
