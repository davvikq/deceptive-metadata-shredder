"""Right-side spoof editor panel."""

from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_SYSTEM_DATE_KEYS: frozenset[str] = frozenset({"FileModifyDate", "FileAccessDate", "FileCreateDate"})
try:
    from faker import Faker
except ImportError:
    Faker = None

from dms.core import geo_validator
from dms.core.device_db import get_all_makes, get_models_by_make, get_random_vintage
from dms.core.models import FileReport, MetaField, parse_metadata_datetime
from dms.core.spoofer import WRITABLE_DATE_FORMATS, get_writable_date_tags
from dms.interfaces.gui.theme import COLORS, tr
from dms.interfaces.gui.widgets.glass_card import GlassCard
from dms.interfaces.gui.widgets.map_widget import MapWidget

faker = Faker() if Faker is not None else None


class SpoofEditor(GlassCard):
    """Per-field spoof controls (GPS, device, dates, text)."""

    applyRequested = Signal(object, object, object)
    closeRequested = Signal()
    validationError = Signal(str)

    def __init__(self, locale_getter, parent=None):
        super().__init__(parent)
        self.locale_getter = locale_getter
        self.report: FileReport | None = None
        self.field: MetaField | None = None
        self.mode = "text"

        self._title_font = QFont("Segoe UI", 16, QFont.Bold)
        self._label_font = QFont("Segoe UI", 11, QFont.DemiBold)
        self._text_font = QFont("Segoe UI", 10)
        self._mono_font = QFont("Cascadia Code", 10)
        self._button_font = QFont("Segoe UI", 10, QFont.Medium)

        self.setMaximumWidth(300)
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.title_label = QLabel("-", self)
        self.title_label.setFont(self._title_font)
        header.addWidget(self.title_label, 1)

        self.close_button = QPushButton("x", self)
        self.close_button.setFixedSize(28, 28)
        self.close_button.setFont(self._button_font)
        self.close_button.clicked.connect(self.closeRequested)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        layout.addLayout(self.body, 1)

        self.apply_button = QPushButton(self)
        self.apply_button.setFixedHeight(38)
        self.apply_button.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        self.apply_button.setStyleSheet(
            f"QPushButton {{ background:{COLORS['accent']}; border-color:{COLORS['accent']}; color: #f8fafc; }}"
            f"QPushButton:hover {{ background:{COLORS['accent_hover']}; color: #f8fafc; }}"
        )
        self.apply_button.clicked.connect(self._emit_apply)
        layout.addWidget(self.apply_button)

    def _locale(self) -> str:
        return self.locale_getter()

    def _t(self, key: str, **kwargs) -> str:
        return tr(self._locale(), key, **kwargs)

    def set_context(self, report: FileReport, field: MetaField) -> None:
        self.report = report
        self.field = field
        self.mode = self._detect_mode(field)
        self.apply_button.setEnabled(True)
        self._clear_dynamic()
        self.title_label.setText(f"{self._t('edit')} {field.label}")

        if self.mode == "gps":
            self._build_gps()
        elif self.mode == "device":
            self._build_device()
        elif self.mode == "dates":
            self._build_dates()
        else:
            self._build_textual()

        self.refresh_locale()

    def refresh_locale(self) -> None:
        if self.field is not None:
            self.title_label.setText(f"{self._t('edit')} {self.field.label}")
        self.apply_button.setText(self._t("apply"))
        if hasattr(self, "_section_label") and getattr(self, "_section_key", None):
            self._section_label.setText(self._t(self._section_key))
        if hasattr(self, "smart_button"):
            self.smart_button.setText(self._t("smart_spoof"))
        if hasattr(self, "vintage_box"):
            self.vintage_box.setText(self._t("vintage_mode"))
        if hasattr(self, "random_button"):
            self.random_button.setText(self._t("random"))
        if hasattr(self, "clear_button"):
            self.clear_button.setText(self._t("clear"))
        if hasattr(self, "date_keep"):
            self.date_keep.setText(self._t("keep"))
            self.date_remove.setText(self._t("remove"))
            self.date_random.setText(self._t("random"))
            self.date_shift.setText(self._t("shift"))
            self._update_date_preview()
        if hasattr(self, "readonly_warning"):
            self.readonly_warning.setText(self._t("date_readonly_warning"))
        if hasattr(self, "country_label") and hasattr(self, "lat_edit"):
            try:
                self._update_country_label(float(self.lat_edit.text()), float(self.lon_edit.text()))
            except (ValueError, AttributeError):
                pass

    def _clear_dynamic(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            nested = item.layout()
            if nested is not None:
                while nested.count():
                    child = nested.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def _section_title(self, text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setFont(self._label_font)
        label.setStyleSheet("color:#f8fafc;")
        return label

    def _detect_mode(self, field: MetaField) -> str:
        lowered = field.key.lower()
        if field.category == "gps":
            return "gps"
        if field.category == "device":
            return "device"
        if field.category == "dates":
            return "dates"
        if field.category == "author":
            return "text"
        if any(kw in lowered for kw in ("latitude", "longitude", "gpsaltitude", "gpsposition", "gpsimgdirection", "gpsspeed", "gpsdestbearing")):
            return "gps"
        if any(kw in lowered for kw in ("date", "time", "created", "modified")):
            return "dates"
        return "text"

    def _build_gps(self) -> None:
        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._section_label = self._section_title(self._t("gps_label"), wrapper)
        self._section_key = "gps_label"
        layout.addWidget(self._section_label)

        lat_field = self.report.by_key().get("GPSLatitude") if self.report else None
        lon_field = self.report.by_key().get("GPSLongitude") if self.report else None
        try:
            lat = float(lat_field.value) if lat_field and lat_field.value not in (None, "") else 41.3111
        except (TypeError, ValueError):
            lat = 41.3111
        try:
            lon = float(lon_field.value) if lon_field and lon_field.value not in (None, "") else 69.2797
        except (TypeError, ValueError):
            lon = 69.2797

        self.map_widget = MapWidget(wrapper)
        self.map_widget.setMinimumHeight(200)
        self.map_widget.coordinates_selected.connect(self._on_map_click)
        self.map_widget.set_position(lat, lon)
        layout.addWidget(self.map_widget)

        row = QHBoxLayout()
        self.lat_edit = QLineEdit(f"{lat:.6f}", wrapper)
        self.lat_edit.setFont(self._text_font)
        self.lon_edit = QLineEdit(f"{lon:.6f}", wrapper)
        self.lon_edit.setFont(self._text_font)
        self.smart_button = QPushButton(wrapper)
        self.smart_button.setFont(self._button_font)
        self.smart_button.clicked.connect(self._smart_spoof)
        row.addWidget(self.lat_edit)
        row.addWidget(self.lon_edit)
        row.addWidget(self.smart_button)
        layout.addLayout(row)

        self.country_label = QLabel(wrapper)
        self.country_label.setFont(QFont("Segoe UI", 10))
        self.country_label.setStyleSheet("color:#94a3b8;")
        layout.addWidget(self.country_label)
        self._update_country_label(lat, lon)
        self.body.addWidget(wrapper)

    def _build_device(self) -> None:
        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._section_label = self._section_title(self._t("device_label"), wrapper)
        self._section_key = "device_label"
        layout.addWidget(self._section_label)

        make_field = next((item for item in self.report.fields if item.category == "device" and item.key == "Make"), None)
        model_field = next((item for item in self.report.fields if item.category == "device" and item.key == "Model"), None)

        self.make_combo = QComboBox(wrapper)
        self.make_combo.setFont(self._text_font)
        self.make_combo.addItems(get_all_makes())
        if make_field and str(make_field.value):
            self.make_combo.setCurrentText(str(make_field.value))
        self.make_combo.currentTextChanged.connect(self._update_models)
        layout.addWidget(self.make_combo)

        self.model_combo = QComboBox(wrapper)
        self.model_combo.setFont(self._text_font)
        layout.addWidget(self.model_combo)

        self.vintage_box = QCheckBox(wrapper)
        self.vintage_box.setFont(self._text_font)
        self.vintage_box.toggled.connect(self._toggle_vintage)
        layout.addWidget(self.vintage_box)

        self.preview = QTextEdit(wrapper)
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(110)
        self.preview.setFont(self._mono_font)
        self.preview.setStyleSheet("color:#a5f3fc;")
        layout.addWidget(self.preview)

        self.body.addWidget(wrapper)
        preferred_model = str(model_field.value) if model_field and model_field.value else None
        self._update_models(self.make_combo.currentText(), preferred_model=preferred_model)

    def _build_dates(self) -> None:
        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._section_label = self._section_title(self._t("dates_label"), wrapper)
        self._section_key = "dates_label"
        layout.addWidget(self._section_label)

        self._is_system_date = self.field is not None and self.field.key in _SYSTEM_DATE_KEYS

        self.current_date = QLabel(str(self.field.value), wrapper)
        self.current_date.setFont(QFont("Segoe UI", 10))
        self.current_date.setStyleSheet("color:#94a3b8;")
        layout.addWidget(self.current_date)

        self.date_group = QButtonGroup(wrapper)
        grid = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()
        self.date_keep = QRadioButton(wrapper)
        self.date_remove = QRadioButton(wrapper)
        self.date_random = QRadioButton(wrapper)
        self.date_shift = QRadioButton(wrapper)
        for button in (self.date_keep, self.date_remove, self.date_random, self.date_shift):
            button.setFont(self._text_font)
            self.date_group.addButton(button)
            button.toggled.connect(self._update_date_preview)
        self.date_keep.setChecked(True)
        left.addWidget(self.date_keep)
        left.addWidget(self.date_random)
        right.addWidget(self.date_remove)
        right.addWidget(self.date_shift)
        grid.addLayout(left)
        grid.addLayout(right)
        layout.addLayout(grid)

        if self._is_system_date:
            self.date_remove.setVisible(False)  # OS file times: exiftool can't delete, only overwrite

        self.shift_slider = QSlider(Qt.Horizontal, wrapper)
        self.shift_slider.setRange(-365, 365)
        self.shift_slider.valueChanged.connect(self._update_date_preview)
        layout.addWidget(self.shift_slider)

        self.preview_label = QLabel(wrapper)
        self.preview_label.setFont(QFont("Segoe UI", 10))
        self.preview_label.setStyleSheet("color:#a5f3fc;")
        layout.addWidget(self.preview_label)

        self.datetime_edit = QDateTimeEdit(wrapper)
        self.datetime_edit.setFont(self._text_font)
        self.datetime_edit.setCalendarPopup(True)
        self.datetime_edit.setDisplayFormat("yyyy:MM:dd HH:mm:ss")
        _parsed = parse_metadata_datetime(self.field.value) if self.field else None
        if _parsed is not None:
            self.datetime_edit.setDateTime(
                QDateTime(_parsed.year, _parsed.month, _parsed.day,
                          _parsed.hour, _parsed.minute, _parsed.second)
            )
        else:
            self.datetime_edit.setDateTime(QDateTime.currentDateTime())
        self.datetime_edit.setVisible(self._is_system_date)
        layout.addWidget(self.datetime_edit)

        self.readonly_warning = QLabel(self._t("date_readonly_warning"), wrapper)
        self.readonly_warning.setWordWrap(True)
        self.readonly_warning.setFont(QFont("Segoe UI", 10, QFont.Medium))
        self.readonly_warning.setStyleSheet(f"color:{COLORS['warning']};")
        layout.addWidget(self.readonly_warning)

        self.body.addWidget(wrapper)
        self._update_date_writable_state()
        self._update_date_preview()

    def _build_textual(self) -> None:
        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title_key = "author_label" if self.field and self.field.category == "author" else None
        title_text = self._t(title_key) if title_key else self.field.label
        self._section_label = self._section_title(title_text, wrapper)
        self._section_key = title_key
        layout.addWidget(self._section_label)

        row = QHBoxLayout()
        self.text_edit = QLineEdit("" if self.field is None or self.field.value is None else str(self.field.value), wrapper)
        self.text_edit.setFont(self._text_font)
        row.addWidget(self.text_edit, 1)

        self.random_button = QPushButton(wrapper)
        self.random_button.setMinimumWidth(72)
        self.random_button.setFont(self._button_font)
        self.random_button.clicked.connect(self._randomize_text)
        row.addWidget(self.random_button)

        self.clear_button = QPushButton(wrapper)
        self.clear_button.setMinimumWidth(64)
        self.clear_button.setFont(self._button_font)
        self.clear_button.clicked.connect(lambda: self.text_edit.setText(""))
        row.addWidget(self.clear_button)
        layout.addLayout(row)

        self.body.addWidget(wrapper)

    def _update_country_label(self, lat: float, lon: float) -> None:
        country = geo_validator.get_country(lat, lon) or "??"
        self.country_label.setText(f"{self._t('detected')}: {country} -> {self._t('stays_in')} {country}")

    def _on_map_click(self, lat: float, lon: float) -> None:
        self.lat_edit.setText(f"{lat:.6f}")
        self.lon_edit.setText(f"{lon:.6f}")
        self.map_widget.set_spoof_marker(lat, lon)
        self._update_country_label(lat, lon)

    def _smart_spoof(self) -> None:
        try:
            lat = float(self.lat_edit.text())
            lon = float(self.lon_edit.text())
        except ValueError:
            self.validationError.emit("gps_invalid_coords")
            return
        new_lat, new_lon = geo_validator.smart_spoof(lat, lon)
        self._on_map_click(new_lat, new_lon)

    def _update_models(self, make: str, preferred_model: str | None = None) -> None:
        devices = get_models_by_make(make)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems([device.model for device in devices])
        if preferred_model:
            index = self.model_combo.findText(preferred_model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)
        self._refresh_device_preview()

    def _toggle_vintage(self, enabled: bool) -> None:
        if enabled:
            device = get_random_vintage()
            self.make_combo.setCurrentText(device.make)
            self._update_models(device.make, preferred_model=device.model)
        else:
            self._update_models(self.make_combo.currentText())

    def _refresh_device_preview(self) -> None:
        devices = get_models_by_make(self.make_combo.currentText())
        current = next((item for item in devices if item.model == self.model_combo.currentText()), None)
        if current is None and devices:
            current = devices[0]
        if current is None:
            self.preview.clear()
            return
        lines = [f"{key}: {value}" for key, value in list(current.exif_overrides.items())[:5]]
        self.preview.setPlainText("\n".join(lines))

    def _date_anchor(self) -> datetime:
        parsed = parse_metadata_datetime(self.field.value) if self.field else None
        return parsed or datetime.now(timezone.utc).replace(tzinfo=None)

    def _update_date_preview(self) -> None:
        anchor = self._date_anchor()
        if self.date_remove.isChecked():
            preview = "-"
        elif self.date_random.isChecked():
            preview = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=180)).strftime("%Y:%m:%d %H:%M:%S")
        elif self.date_shift.isChecked():
            preview = (anchor + timedelta(days=self.shift_slider.value())).strftime("%Y:%m:%d %H:%M:%S")
        else:
            preview = anchor.strftime("%Y:%m:%d %H:%M:%S")
        self.preview_label.setText(preview)
        self.shift_slider.setVisible(self.date_shift.isChecked())

    def _randomize_text(self) -> None:
        if self.field and self.field.category == "author":
            self.text_edit.setText(faker.name() if faker is not None else "John Smith")
            return
        if self.field and any(token in self.field.key.lower() for token in ("serial", "unique", "id")):
            length = max(len(self.text_edit.text()), 8)
            alphabet = string.hexdigits.upper()[:16]
            self.text_edit.setText("".join(random.choice(alphabet) for _ in range(length)))
            return
        self.text_edit.setText(faker.word() if faker is not None else "metadata")

    def _date_payload(self) -> tuple[dict[str, object], dict[str, str]]:
        anchor = self._date_anchor()

        # __dms_system_date__ → MainWindow routes to spoof/set_filesystem_dates (not EXIF writer).
        if getattr(self, "_is_system_date", False):
            if self.date_random.isChecked():
                return {"__dms_system_date__": None}, {self.field.key: "random"}
            if self.date_shift.isChecked():
                shifted = anchor + timedelta(days=self.shift_slider.value())
                fmt = shifted.strftime("%Y:%m:%d %H:%M:%S")
                return {"__dms_system_date__": fmt}, {self.field.key: fmt}
            qt_dt = self.datetime_edit.dateTime()
            custom_dt = datetime(
                qt_dt.date().year(), qt_dt.date().month(), qt_dt.date().day(),
                qt_dt.time().hour(), qt_dt.time().minute(), qt_dt.time().second(),
            )
            fmt = custom_dt.strftime("%Y:%m:%d %H:%M:%S")
            return {"__dms_system_date__": fmt}, {self.field.key: fmt}

        if self.date_remove.isChecked():
            return (
                {"__dms_dates_remove__": True, "__dms_date_kind__": "dates"},
                {field.key: "" for field in self.report.fields if field.category == "dates"},
            )
        if self.date_random.isChecked():
            anchor = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=random.randint(30, 2000))
        elif self.date_shift.isChecked():
            anchor = anchor + timedelta(days=self.shift_slider.value())
        formatted = anchor.strftime("%Y:%m:%d %H:%M:%S")
        writes = {
            "__dms_date_kind__": "dates",
            "__dms_date_value__": formatted,
        }
        display = {field.key: formatted for field in self.report.fields if field.category == "dates"}
        return writes, display

    def _update_date_writable_state(self) -> None:
        if self.report is None or self.field is None or self.mode != "dates":
            return
        # Bulk date edit skips Composite (exiftool-derived); already-spoofed row was writable.
        is_writable = (not self.field.is_computed) or (self.field.status == "spoofed")
        self.readonly_warning.setVisible(not is_writable)
        self.apply_button.setEnabled(is_writable)

    def _gps_payload(self) -> tuple[dict[str, object], dict[str, str]]:
        lat = float(self.lat_edit.text())
        lon = float(self.lon_edit.text())
        writes = {"GPSLatitude": lat, "GPSLongitude": lon}
        display = {"GPSLatitude": f"{lat:.6f}", "GPSLongitude": f"{lon:.6f}"}
        return writes, display

    def _device_payload(self) -> tuple[dict[str, object], dict[str, str]]:
        device = next((item for item in get_models_by_make(self.make_combo.currentText()) if item.model == self.model_combo.currentText()), None)
        if device is None:
            return {}, {}
        writes: dict[str, object] = {"Make": device.make, "Model": device.model}
        if device.software:
            writes["Software"] = device.software
        writes.update(device.exif_overrides)
        display = {key.split(".")[-1].split(":")[-1]: str(value) for key, value in writes.items()}
        return writes, display

    def _text_payload(self) -> tuple[dict[str, object], dict[str, str]]:
        if self.field is None:
            return {}, {}
        value = self.text_edit.text()
        return {self.field.exiftool_tag: value}, {self.field.key: value}

    def _emit_apply(self) -> None:
        if self.field is None:
            return
        try:
            if self.mode == "gps":
                writes, display = self._gps_payload()
            elif self.mode == "device":
                writes, display = self._device_payload()
            elif self.mode == "dates":
                writes, display = self._date_payload()
            else:
                writes, display = self._text_payload()
        except ValueError:
            self.validationError.emit("gps_invalid_coords")
            return
        except Exception:
            self.validationError.emit("unexpected_error")
            return
        self.applyRequested.emit(self.field, writes, display)
