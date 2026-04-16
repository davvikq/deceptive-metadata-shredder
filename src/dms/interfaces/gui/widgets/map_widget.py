"""Offline coordinate map widget using pure Qt painting.

No network requests, no external CDN, no WebEngine — fully offline.
Draws a world grid with continent outlines, markers, and click-to-place.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

_CONTINENT_POLYGONS: list[list[tuple[float, float]]] | None = None


def _load_continent_outlines() -> list[list[tuple[float, float]]]:
    """Load simplified country outlines from the bundled GeoJSON."""
    global _CONTINENT_POLYGONS
    if _CONTINENT_POLYGONS is not None:
        return _CONTINENT_POLYGONS

    geojson_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "countries.geojson"
    polygons: list[list[tuple[float, float]]] = []
    if not geojson_path.exists():
        _CONTINENT_POLYGONS = polygons
        return polygons

    try:
        data = json.loads(geojson_path.read_text(encoding="utf-8"))
        for feature in data.get("features", []):
            geom = feature.get("geometry", {})
            geom_type = geom.get("type", "")
            coords = geom.get("coordinates", [])
            if geom_type == "Polygon":
                for ring in coords[:1]:
                    simplified = ring[::max(1, len(ring) // 80)]
                    if len(simplified) >= 3:
                        polygons.append([(pt[0], pt[1]) for pt in simplified])
            elif geom_type == "MultiPolygon":
                for polygon in coords:
                    for ring in polygon[:1]:
                        simplified = ring[::max(1, len(ring) // 80)]
                        if len(simplified) >= 3:
                            polygons.append([(pt[0], pt[1]) for pt in simplified])
    except Exception:
        pass

    _CONTINENT_POLYGONS = polygons
    return polygons


class MapWidget(QWidget):
    """Offline coordinate map with country outlines, click-to-place markers."""

    coordinates_selected = Signal(float, float)

    BG_COLOR = QColor("#12121f")
    GRID_COLOR = QColor(255, 255, 255, 18)
    LAND_FILL = QColor(40, 40, 70, 120)
    LAND_BORDER = QColor(99, 102, 241, 50)
    MARKER_COLOR = QColor("#ef4444")
    SPOOF_COLOR = QColor("#60a5fa")
    CROSSHAIR_COLOR = QColor(255, 255, 255, 60)
    LABEL_COLOR = QColor("#94a3b8")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._lat = 0.0
        self._lon = 0.0
        self._spoof_lat: float | None = None
        self._spoof_lon: float | None = None
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._dragging = False
        self._drag_start = QPointF()
        self._pan_start_x = 0.0
        self._pan_start_y = 0.0
        # Land path: rebuild only when viewport (size, zoom, pan) changes.
        self._land_path_cache: QPainterPath | None = None
        self._land_cache_key: tuple[int, int, float, float, float] | None = None
        self.setMinimumSize(200, 120)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

    def _invalidate_land_cache(self) -> None:
        self._land_path_cache = None
        self._land_cache_key = None

    def set_position(self, lat: float, lon: float) -> None:
        self._lat = lat
        self._lon = lon
        self._center_on(lat, lon)
        self._invalidate_land_cache()
        self.update()

    def set_spoof_marker(self, lat: float, lon: float) -> None:
        self._spoof_lat = lat
        self._spoof_lon = lon
        self.update()

    def _center_on(self, lat: float, lon: float) -> None:
        w, h = self.width(), self.height()
        px, py = self._geo_to_pixel(lat, lon, w, h, 0.0, 0.0)
        self._pan_x = w / 2 - px
        self._pan_y = h / 2 - py

    def _geo_to_pixel(self, lat: float, lon: float, w: int, h: int, pan_x: float = 0.0, pan_y: float = 0.0) -> tuple[float, float]:
        x = (lon + 180) / 360 * w * self._zoom + pan_x
        lat_rad = math.radians(max(-85, min(85, lat)))
        merc_y = math.log(math.tan(math.pi / 4 + lat_rad / 2))
        y = (0.5 - merc_y / (2 * math.pi)) * h * self._zoom + pan_y
        return x, y

    def _pixel_to_geo(self, px: float, py: float, w: int, h: int) -> tuple[float, float]:
        x = (px - self._pan_x) / (w * self._zoom)
        y = (py - self._pan_y) / (h * self._zoom)
        lon = x * 360 - 180
        merc_y = (0.5 - y) * 2 * math.pi
        lat = math.degrees(2 * math.atan(math.exp(merc_y)) - math.pi / 2)
        return max(-85, min(85, lat)), max(-180, min(180, lon))

    def _ensure_land_path(self, w: int, h: int) -> QPainterPath | None:
        key: tuple[int, int, float, float, float] = (w, h, self._zoom, self._pan_x, self._pan_y)
        if self._land_path_cache is not None and self._land_cache_key == key:
            return self._land_path_cache

        path = QPainterPath()
        polygons = _load_continent_outlines()
        for coords in polygons:
            points: list[QPointF] = []
            for lon, lat in coords:
                px, py = self._geo_to_pixel(lat, lon, w, h, self._pan_x, self._pan_y)
                points.append(QPointF(px, py))
            if len(points) >= 3:
                path.addPolygon(QPolygonF(points))
        self._land_path_cache = path
        self._land_cache_key = key
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        painter.fillRect(self.rect(), self.BG_COLOR)

        self._draw_land(painter, w, h)
        self._draw_grid(painter, w, h)
        self._draw_markers(painter, w, h)
        self._draw_labels(painter, w, h)

        painter.end()

    def resizeEvent(self, event) -> None:
        self._invalidate_land_cache()
        super().resizeEvent(event)

    def _draw_land(self, painter: QPainter, w: int, h: int) -> None:
        land = self._ensure_land_path(w, h)
        if land is None or land.isEmpty():
            return
        painter.setPen(QPen(self.LAND_BORDER, 0.5))
        painter.setBrush(QBrush(self.LAND_FILL))
        painter.drawPath(land)

    def _draw_grid(self, painter: QPainter, w: int, h: int) -> None:
        pen = QPen(self.GRID_COLOR, 0.5)
        painter.setPen(pen)
        font = QFont("Segoe UI", 7)
        painter.setFont(font)

        for lon in range(-180, 181, 30):
            x1, y1 = self._geo_to_pixel(85, lon, w, h, self._pan_x, self._pan_y)
            x2, y2 = self._geo_to_pixel(-85, lon, w, h, self._pan_x, self._pan_y)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            if 0 <= x1 <= w:
                painter.setPen(QPen(self.LABEL_COLOR, 1))
                painter.drawText(QPointF(x1 + 2, h - 4), f"{lon}\u00b0")
                painter.setPen(pen)

        for lat in range(-60, 81, 30):
            x1, y1 = self._geo_to_pixel(lat, -180, w, h, self._pan_x, self._pan_y)
            x2, y2 = self._geo_to_pixel(lat, 180, w, h, self._pan_x, self._pan_y)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            if 0 <= y1 <= h:
                painter.setPen(QPen(self.LABEL_COLOR, 1))
                painter.drawText(QPointF(4, y1 - 2), f"{lat}\u00b0")
                painter.setPen(pen)

    def _draw_marker(self, painter: QPainter, lat: float, lon: float, w: int, h: int, color: QColor, radius: float) -> None:
        px, py = self._geo_to_pixel(lat, lon, w, h, self._pan_x, self._pan_y)
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 140)))
        painter.drawEllipse(QPointF(px, py), radius, radius)
        painter.setPen(QPen(color, 1))
        painter.drawLine(QPointF(px - radius - 3, py), QPointF(px + radius + 3, py))
        painter.drawLine(QPointF(px, py - radius - 3), QPointF(px, py + radius + 3))

    def _draw_markers(self, painter: QPainter, w: int, h: int) -> None:
        self._draw_marker(painter, self._lat, self._lon, w, h, self.MARKER_COLOR, 6)
        if self._spoof_lat is not None and self._spoof_lon is not None:
            self._draw_marker(painter, self._spoof_lat, self._spoof_lon, w, h, self.SPOOF_COLOR, 7)

    def _draw_labels(self, painter: QPainter, w: int, h: int) -> None:
        font = QFont("Cascadia Code", 9)
        painter.setFont(font)
        painter.setPen(QPen(self.MARKER_COLOR, 1))
        px, py = self._geo_to_pixel(self._lat, self._lon, w, h, self._pan_x, self._pan_y)
        painter.drawText(QPointF(px + 10, py - 4), f"{self._lat:.4f}, {self._lon:.4f}")
        if self._spoof_lat is not None and self._spoof_lon is not None:
            painter.setPen(QPen(self.SPOOF_COLOR, 1))
            spx, spy = self._geo_to_pixel(self._spoof_lat, self._spoof_lon, w, h, self._pan_x, self._pan_y)
            painter.drawText(QPointF(spx + 10, spy - 4), f"{self._spoof_lat:.4f}, {self._spoof_lon:.4f}")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ShiftModifier:
                self._dragging = True
                self._drag_start = event.position()
                self._pan_start_x = self._pan_x
                self._pan_start_y = self._pan_y
                self.setCursor(Qt.ClosedHandCursor)
            else:
                lat, lon = self._pixel_to_geo(event.position().x(), event.position().y(), self.width(), self.height())
                self._spoof_lat = round(lat, 6)
                self._spoof_lon = round(lon, 6)
                self.coordinates_selected.emit(self._spoof_lat, self._spoof_lon)
                self.update()
        elif event.button() == Qt.MiddleButton:
            self._dragging = True
            self._drag_start = event.position()
            self._pan_start_x = self._pan_x
            self._pan_start_y = self._pan_y
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            delta = event.position() - self._drag_start
            self._pan_x = self._pan_start_x + delta.x()
            self._pan_y = self._pan_start_y + delta.y()
            self._invalidate_land_cache()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CrossCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        old_zoom = self._zoom
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.5, min(20.0, self._zoom * factor))

        mouse_pos = event.position()
        self._pan_x = mouse_pos.x() - (mouse_pos.x() - self._pan_x) * (self._zoom / old_zoom)
        self._pan_y = mouse_pos.y() - (mouse_pos.y() - self._pan_y) * (self._zoom / old_zoom)
        self._invalidate_land_cache()
        self.update()
        event.accept()
