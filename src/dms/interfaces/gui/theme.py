"""PySide6 GUI theme, translations, and presentation helpers."""

from __future__ import annotations

COLORS = {
    "bg_primary": "#0d0d1a",
    "bg_secondary": "#12121f",
    "surface": "rgba(255, 255, 255, 13)",
    "surface_hover": "rgba(255, 255, 255, 20)",
    "border": "rgba(255, 255, 255, 25)",
    "accent": "#6366f1",
    "accent_hover": "#4f46e5",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "text_primary": "#f8fafc",
    "text_secondary": "#94a3b8",
    "text_mono": "#a5f3fc",
}

_FONT_STACK = '"Segoe UI", "Arial", sans-serif'

GLOBAL_QSS = f"""
QWidget {{
    font-family: {_FONT_STACK};
}}

QMainWindow, QWidget#central {{
    background-color: #0d0d1a;
    color: #f8fafc;
    font-family: {_FONT_STACK};
}}

QFrame#GlassCard {{
    color: #f8fafc;
    font-family: {_FONT_STACK};
}}

QLabel {{
    color: #f8fafc;
    font-family: {_FONT_STACK};
}}

QLabel#lang_btn {{
    color: #94a3b8;
    padding: 4px 10px;
    border-radius: 8px;
    border: 1px solid transparent;
    font-family: {_FONT_STACK};
}}

QLabel#lang_btn[active="true"] {{
    color: #f8fafc;
    background: #6366f1;
    border: 1px solid #6366f1;
    font-family: {_FONT_STACK};
}}

QLabel#lang_btn:hover {{
    color: #f8fafc;
    border: 1px solid rgba(255,255,255,0.2);
    font-family: {_FONT_STACK};
}}

QPushButton {{
    color: #f8fafc;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 10px;
    background: rgba(255,255,255,0.06);
    padding: 8px 14px;
    font-family: {_FONT_STACK};
}}

QPushButton:hover {{
    background: rgba(255,255,255,0.10);
    color: #f8fafc;
}}

QPushButton:checked {{
    background: #6366f1;
    border-color: #6366f1;
    color: #f8fafc;
}}

QLineEdit, QComboBox, QTextEdit {{
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    color: #f8fafc;
    padding: 8px 10px;
    selection-background-color: rgba(99,102,241,0.4);
    font-family: {_FONT_STACK};
}}

QComboBox QAbstractItemView {{
    background: #16182a;
    color: #f8fafc;
    border: 1px solid rgba(255,255,255,0.14);
    selection-background-color: rgba(99,102,241,0.25);
    font-family: {_FONT_STACK};
}}

QTreeWidget {{
    background: transparent;
    border: none;
    outline: none;
    color: #f8fafc;
    font-family: {_FONT_STACK};
}}

QTreeWidget::item {{
    background: transparent;
    height: 34px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    color: #f8fafc;
}}

QTreeWidget::item:hover {{
    background: rgba(255,255,255,0.05);
    color: #f8fafc;
}}

QTreeWidget::item:selected {{
    background: rgba(99,102,241,0.15);
    color: #f8fafc;
}}

QTreeWidget::branch {{
    background: transparent;
}}

QHeaderView::section {{
    background: transparent;
    color: #94a3b8;
    border: none;
    padding: 6px 8px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    font-family: {_FONT_STACK};
}}

QScrollBar:vertical {{
    background: transparent;
    color: #f8fafc;
    width: 4px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: rgba(99, 102, 241, 0.6);
    color: #f8fafc;
    border-radius: 2px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(99, 102, 241, 1.0);
    color: #f8fafc;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    height: 0;
}}

QToolTip {{
    background: #1e1e30;
    color: #f8fafc;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    font-family: {_FONT_STACK};
}}
"""

LOCALES: dict[str, dict[str, str]] = {
    "en": {
        "all": "All",
        "app_title": "DMS",
        "applied": "Applied",
        "apply": "Apply",
        "author_dates": "Author & Dates",
        "author_label": "Author",
        "back": "Back",
        "batch_add_more": "Add more files",
        "batch_analyzing": "Analyzing\u2026",
        "batch_apply": "Run batch",
        "batch_complete": "Batch finished: {n} file(s)",
        "batch_done": "Done",
        "batch_error": "Error",
        "batch_hint": "Add files, choose a mode, then run.",
        "batch_processing": "Processing\u2026",
        "batch_processing_btn": "Processing\u2026",
        "batch_ready": "Ready",
        "batch_save_all": "Choose output folder",
        "batch_title": "Batch",
        "batch_waiting": "Waiting",
        "browse_file": "Browse File",
        "clean_residual_body": "Remove {n} remaining sensitive tag(s)?",
        "clean_residual_btn": "Clean residual",
        "clean_residual_confirm": "Remove {n}",
        "clean_residual_nothing": "No residual sensitive tags found.",
        "clean_residual_title": "Clean residual tags",
        "clean_residual_toast": "Cleaned {n} residual tag(s)",
        "clear": "Clear",
        "compare_back": "Back",
        "compare_btn": "Compare",
        "menu_language": "Language",
        "compare_cleaned": "Cleaned",
        "compare_hide_unchanged": "Hide unchanged ({n})",
        "compare_injected": "(injected)",
        "compare_injected_badge": "NEW",
        "compare_not_present": "(not present)",
        "compare_original": "Original",
        "compare_removed": "(removed)",
        "compare_save": "Save copy",
        "compare_show_unchanged": "Show unchanged ({n})",
        "compare_summary": "Removed: {r}  \u00b7  Changed: {s}  \u00b7  Unchanged: {u}",
        "compare_title": "Compare metadata",
        "computed_tooltip": "This field is computed by exiftool and cannot be directly removed",
        "date_readonly_warning": "This date is managed by the OS \u2014 use randomize or the date editor.",
        "dates_label": "Dates",
        "detected": "Detected",
        "device": "Device",
        "device_label": "Device",
        "dms_output_add": "Add anyway",
        "dms_output_body": "Some files look like prior DMS exports. Add them anyway?",
        "dms_output_cancel": "Cancel",
        "dms_output_skip": "Skip similar",
        "dms_output_title": "Prior export detected",
        "drop_formats": "JPG PNG HEIC TIFF WebP RAW PDF DOCX MP4",
        "drop_subtitle": "Drop a file to inspect its hidden data",
        "edit": "Edit:",
        "field_removed": "Field removed",
        "full_title": "Deceptive Metadata Shredder",
        "gps": "GPS & Location",
        "gps_label": "GPS Location",
        "gps_spoofed": "GPS spoofed successfully",
        "important": "Important",
        "keep": "Keep",
        "loading": "Processing...",
        "mode_remove": "Remove metadata",
        "mode_spoof": "Smart spoof",
        "mode_spoof_clean": "Spoof then clean",
        "other": "Other",
        "progress_author": "Spoofing author\u2026",
        "progress_dates": "Spoofing dates\u2026",
        "progress_device": "Spoofing device\u2026",
        "progress_gps": "Smart spoof\u2026",
        "random": "Random",
        "raw_banner": "RAW: some embedded tags may remain \u2014 prefer DNG for full control.",
        "raw_tip": "Tip: convert to DNG for maximum metadata control.",
        "raw_warning_body": "RAW formats may retain some embedded metadata. Continue?",
        "raw_warning_cancel": "Cancel",
        "raw_warning_proceed": "Continue",
        "raw_warning_title": "RAW file",
        "region_tooltip": "Embedded in Apple XMP block \u2014 will be removed with full region cleanup",
        "remove": "Remove",
        "remove_all": "Remove All",
        "risk_clean": "Clean",
        "risk_high": "High Risk",
        "risk_low": "Low Risk",
        "risk_medium": "Medium Risk",
        "save_copy": "Save Copy",
        "save_dialog_title": "Save cleaned copy",
        "saved_to": "File saved to: {path}",
        "saved_toast": "Saved {filename}",
        "sensitive": "sensitive",
        "shift": "Shift",
        "smart_spoof": "Smart Spoof",
        "smart_spoof_skip_gps_no_source": "GPS spoof skipped \u2014 no valid latitude/longitude pair in file.",
        "smart_spoof_skip_gps_no_country_data": "GPS spoof skipped \u2014 countries.geojson was not found.",
        "smart_spoof_skip_device_no_candidates": "Device spoof skipped \u2014 no replacement devices were available.",
        "smart_spoof_partial_gps_failed": "GPS spoof partially failed.",
        "smart_spoof_partial_device_failed": "Device spoof partially failed.",
        "smart_spoof_partial_dates_failed": "Date spoof partially failed.",
        "smart_spoof_partial_author_failed": "Author spoof partially failed.",
        "smart_spoof_partial_software_failed": "Software spoof partially failed.",
        "smart_spoof_partial_raw_failed": "RAW identifier spoof partially failed.",
        "smart_spoof_partial_region_cleanup_failed": "Region/Face cleanup partially failed.",
        "smart_spoof_partial_non_region_cleanup_failed": "Sensitive tag cleanup partially failed.",
        "status_clean": "CLEAN",
        "status_removed": "CLEAN",
        "status_risk": "RISK",
        "status_spoofed": "SPOOFED",
        "stays_in": "will stay in",
        "system_date_tooltip": "OS file timestamps \u2014 use randomize or edit to overwrite",
        "unsaved_body": "You have unsaved changes. What would you like to do?",
        "unsaved_cancel": "Cancel",
        "unsaved_discard": "Discard",
        "unsaved_save_first": "Save first",
        "unsaved_title": "Unsaved changes",
        "vintage_mode": "Vintage mode",
        "warning_exiftool_linux": "Install exiftool using your distribution package manager.",
        "warning_exiftool_macos": "Install exiftool: brew install exiftool",
        "warning_exiftool_missing": "exiftool.exe not found - place it in the bin/ folder. Download: exiftool.org",
        "warning_exiftool_windows": "exiftool is included - no action needed.",
        "worker_session_busy": "Please wait \u2014 another operation is in progress.",
    },
    "ru": {
        "all": "All",
        "app_title": "DMS",
        "applied": "Applied",
        "apply": "Apply",
        "author_dates": "Author & Dates",
        "author_label": "Author",
        "back": "\u041d\u0430\u0437\u0430\u0434",
        "batch_add_more": "Add more files",
        "batch_analyzing": "Analyzing\u2026",
        "batch_apply": "Run batch",
        "batch_complete": "Batch finished: {n} file(s)",
        "batch_done": "Done",
        "batch_error": "Error",
        "batch_hint": "Add files, choose a mode, then run.",
        "batch_processing": "Processing\u2026",
        "batch_processing_btn": "Processing\u2026",
        "batch_ready": "Ready",
        "batch_save_all": "Choose output folder",
        "batch_title": "Batch",
        "batch_waiting": "Waiting",
        "browse_file": "\u041e\u0431\u0437\u043e\u0440",
        "clean_residual_body": "Remove {n} remaining sensitive tag(s)?",
        "clean_residual_btn": "Clean residual",
        "clean_residual_confirm": "Remove {n}",
        "clean_residual_nothing": "No residual sensitive tags found.",
        "clean_residual_title": "Clean residual tags",
        "clean_residual_toast": "Cleaned {n} residual tag(s)",
        "clear": "Clear",
        "compare_back": "Back",
        "compare_btn": "Compare",
        "menu_language": "\u042f\u0437\u044b\u043a",
        "compare_cleaned": "Cleaned",
        "compare_hide_unchanged": "Hide unchanged ({n})",
        "compare_injected": "(injected)",
        "compare_injected_badge": "NEW",
        "compare_not_present": "(not present)",
        "compare_original": "Original",
        "compare_removed": "(removed)",
        "compare_save": "Save copy",
        "compare_show_unchanged": "Show unchanged ({n})",
        "compare_summary": "Removed: {r}  \u00b7  Changed: {s}  \u00b7  Unchanged: {u}",
        "compare_title": "Compare metadata",
        "computed_tooltip": "This field is computed by exiftool and cannot be directly removed",
        "date_readonly_warning": "This date is managed by the OS \u2014 use randomize or the date editor.",
        "dates_label": "Dates",
        "detected": "Detected",
        "device": "Device",
        "device_label": "Device",
        "dms_output_add": "Add anyway",
        "dms_output_body": "Some files look like prior DMS exports. Add them anyway?",
        "dms_output_cancel": "Cancel",
        "dms_output_skip": "Skip similar",
        "dms_output_title": "Prior export detected",
        "drop_formats": "JPG PNG HEIC TIFF WebP RAW PDF DOCX MP4",
        "drop_subtitle": "\u041f\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u0444\u0430\u0439\u043b, \u0447\u0442\u043e\u0431\u044b \u0443\u0432\u0438\u0434\u0435\u0442\u044c \u0441\u043a\u0440\u044b\u0442\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435",
        "edit": "Edit:",
        "field_removed": "Field removed",
        "full_title": "Deceptive Metadata Shredder",
        "gps": "GPS & Location",
        "gps_label": "GPS Location",
        "gps_spoofed": "GPS spoofed successfully",
        "important": "Important",
        "keep": "Keep",
        "loading": "\u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430\u2026",
        "mode_remove": "Remove metadata",
        "mode_spoof": "Smart spoof",
        "mode_spoof_clean": "Spoof then clean",
        "other": "Other",
        "progress_author": "Spoofing author\u2026",
        "progress_dates": "Spoofing dates\u2026",
        "progress_device": "Spoofing device\u2026",
        "progress_gps": "Smart spoof\u2026",
        "random": "Random",
        "raw_banner": "RAW: some embedded tags may remain \u2014 prefer DNG for full control.",
        "raw_tip": "Tip: convert to DNG for maximum metadata control.",
        "raw_warning_body": "RAW formats may retain some embedded metadata. Continue?",
        "raw_warning_cancel": "Cancel",
        "raw_warning_proceed": "Continue",
        "raw_warning_title": "RAW file",
        "region_tooltip": "Embedded in Apple XMP block \u2014 will be removed with full region cleanup",
        "remove": "Remove",
        "remove_all": "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u0432\u0441\u0451",
        "risk_clean": "Clean",
        "risk_high": "High Risk",
        "risk_low": "Low Risk",
        "risk_medium": "Medium Risk",
        "save_copy": "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043a\u043e\u043f\u0438\u044e",
        "save_dialog_title": "Save cleaned copy",
        "saved_to": "File saved to: {path}",
        "saved_toast": "Saved {filename}",
        "sensitive": "sensitive",
        "shift": "Shift",
        "smart_spoof": "\u0423\u043c\u043d\u0430\u044f \u043f\u043e\u0434\u043c\u0435\u043d\u0430",
        "smart_spoof_skip_gps_no_source": "GPS \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d \u2014 \u0432 \u0444\u0430\u0439\u043b\u0435 \u043d\u0435\u0442 \u043f\u0430\u0440\u044b \u0448\u0438\u0440\u043e\u0442\u0430/\u0434\u043e\u043b\u0433\u043e\u0442\u0430.",
        "smart_spoof_skip_gps_no_country_data": "GPS \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d \u2014 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d countries.geojson.",
        "smart_spoof_skip_device_no_candidates": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 \u0443\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u0430 \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u0430 \u2014 \u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0445 \u043c\u043e\u0434\u0435\u043b\u0435\u0439 \u0434\u043b\u044f \u0437\u0430\u043c\u0435\u043d\u044b.",
        "smart_spoof_partial_gps_failed": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 GPS \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e.",
        "smart_spoof_partial_device_failed": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 \u0443\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e.",
        "smart_spoof_partial_dates_failed": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 \u0434\u0430\u0442 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e.",
        "smart_spoof_partial_author_failed": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 \u0430\u0432\u0442\u043e\u0440\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e.",
        "smart_spoof_partial_software_failed": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 \u041f\u041e \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e.",
        "smart_spoof_partial_raw_failed": "\u041f\u043e\u0434\u043c\u0435\u043d\u0430 RAW-\u0438\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0442\u043e\u0440\u043e\u0432 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e.",
        "smart_spoof_partial_region_cleanup_failed": "\u041e\u0447\u0438\u0441\u0442\u043a\u0430 Region/FaceID выполнена частично.",
        "smart_spoof_partial_non_region_cleanup_failed": "\u041e\u0447\u0438\u0441\u0442\u043a\u0430 \u0447\u0443\u0432\u0441\u0442\u0432\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0445 \u0442\u0435\u0433\u043e\u0432 выполнена частично.",
        "status_clean": "CLEAN",
        "status_removed": "CLEAN",
        "status_risk": "RISK",
        "status_spoofed": "SPOOFED",
        "stays_in": "will stay in",
        "system_date_tooltip": "OS file timestamps \u2014 use randomize or edit to overwrite",
        "unsaved_body": "You have unsaved changes. What would you like to do?",
        "unsaved_cancel": "Cancel",
        "unsaved_discard": "Discard",
        "unsaved_save_first": "Save first",
        "unsaved_title": "Unsaved changes",
        "vintage_mode": "Vintage mode",
        "warning_exiftool_linux": "Install exiftool using your distribution package manager.",
        "warning_exiftool_macos": "Install exiftool: brew install exiftool",
        "warning_exiftool_missing": "exiftool.exe not found - place it in the bin/ folder. Download: exiftool.org",
        "warning_exiftool_windows": "exiftool is included - no action needed.",
        "worker_session_busy": "\u041f\u043e\u0434\u043e\u0436\u0434\u0438\u0442\u0435 \u2014 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f \u0434\u0440\u0443\u0433\u0430\u044f \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u044f.",
    },
    "zh": {
        "all": "All",
        "app_title": "DMS",
        "applied": "Applied",
        "apply": "Apply",
        "author_dates": "Author & Dates",
        "author_label": "Author",
        "back": "\u8fd4\u56de",
        "batch_add_more": "Add more files",
        "batch_analyzing": "Analyzing\u2026",
        "batch_apply": "Run batch",
        "batch_complete": "Batch finished: {n} file(s)",
        "batch_done": "Done",
        "batch_error": "Error",
        "batch_hint": "Add files, choose a mode, then run.",
        "batch_processing": "Processing\u2026",
        "batch_processing_btn": "Processing\u2026",
        "batch_ready": "Ready",
        "batch_save_all": "Choose output folder",
        "batch_title": "Batch",
        "batch_waiting": "Waiting",
        "browse_file": "\u6d4f\u89c8",
        "clean_residual_body": "Remove {n} remaining sensitive tag(s)?",
        "clean_residual_btn": "Clean residual",
        "clean_residual_confirm": "Remove {n}",
        "clean_residual_nothing": "No residual sensitive tags found.",
        "clean_residual_title": "Clean residual tags",
        "clean_residual_toast": "Cleaned {n} residual tag(s)",
        "clear": "Clear",
        "compare_back": "Back",
        "compare_btn": "Compare",
        "menu_language": "\u8bed\u8a00",
        "compare_cleaned": "Cleaned",
        "compare_hide_unchanged": "Hide unchanged ({n})",
        "compare_injected": "(injected)",
        "compare_injected_badge": "NEW",
        "compare_not_present": "(not present)",
        "compare_original": "Original",
        "compare_removed": "(removed)",
        "compare_save": "Save copy",
        "compare_show_unchanged": "Show unchanged ({n})",
        "compare_summary": "Removed: {r}  \u00b7  Changed: {s}  \u00b7  Unchanged: {u}",
        "compare_title": "Compare metadata",
        "computed_tooltip": "This field is computed by exiftool and cannot be directly removed",
        "date_readonly_warning": "This date is managed by the OS \u2014 use randomize or the date editor.",
        "dates_label": "Dates",
        "detected": "Detected",
        "device": "Device",
        "device_label": "Device",
        "dms_output_add": "Add anyway",
        "dms_output_body": "Some files look like prior DMS exports. Add them anyway?",
        "dms_output_cancel": "Cancel",
        "dms_output_skip": "Skip similar",
        "dms_output_title": "Prior export detected",
        "drop_formats": "JPG PNG HEIC TIFF WebP RAW PDF DOCX MP4",
        "drop_subtitle": "\u62d6\u5165\u6587\u4ef6\u4ee5\u67e5\u770b\u9690\u85cf\u6570\u636e",
        "edit": "Edit:",
        "field_removed": "Field removed",
        "full_title": "Deceptive Metadata Shredder",
        "gps": "GPS & Location",
        "gps_label": "GPS Location",
        "gps_spoofed": "GPS spoofed successfully",
        "important": "Important",
        "keep": "Keep",
        "loading": "\u5904\u7406\u4e2d\u2026",
        "mode_remove": "Remove metadata",
        "mode_spoof": "Smart spoof",
        "mode_spoof_clean": "Spoof then clean",
        "other": "Other",
        "progress_author": "Spoofing author\u2026",
        "progress_dates": "Spoofing dates\u2026",
        "progress_device": "Spoofing device\u2026",
        "progress_gps": "Smart spoof\u2026",
        "random": "Random",
        "raw_banner": "RAW: some embedded tags may remain \u2014 prefer DNG for full control.",
        "raw_tip": "Tip: convert to DNG for maximum metadata control.",
        "raw_warning_body": "RAW formats may retain some embedded metadata. Continue?",
        "raw_warning_cancel": "Cancel",
        "raw_warning_proceed": "Continue",
        "raw_warning_title": "RAW file",
        "region_tooltip": "Embedded in Apple XMP block \u2014 will be removed with full region cleanup",
        "remove": "Remove",
        "remove_all": "\u5168\u90e8\u5220\u9664",
        "risk_clean": "Clean",
        "risk_high": "High Risk",
        "risk_low": "Low Risk",
        "risk_medium": "Medium Risk",
        "save_copy": "\u4fdd\u5b58\u526f\u672c",
        "save_dialog_title": "Save cleaned copy",
        "saved_to": "File saved to: {path}",
        "saved_toast": "Saved {filename}",
        "sensitive": "sensitive",
        "shift": "Shift",
        "smart_spoof": "\u667a\u80fd\u4f2a\u88c5",
        "smart_spoof_skip_gps_no_source": "\u5df2\u8df3\u8fc7 GPS \u2014 \u6587\u4ef6\u4e2d\u65e0\u6709\u6548\u7684\u7ecf\u7eac\u5ea6\u5bf9\u3002",
        "smart_spoof_skip_gps_no_country_data": "\u5df2\u8df3\u8fc7 GPS \u4f2a\u88c5 \u2014 \u672a\u627e\u5230 countries.geojson\u3002",
        "smart_spoof_skip_device_no_candidates": "\u5df2\u8df3\u8fc7\u8bbe\u5907\u4f2a\u88c5 \u2014 \u6ca1\u6709\u53ef\u7528\u7684\u66ff\u4ee3\u8bbe\u5907\u3002",
        "smart_spoof_partial_gps_failed": "GPS \u4f2a\u88c5\u90e8\u5206\u5931\u8d25\u3002",
        "smart_spoof_partial_device_failed": "\u8bbe\u5907\u4f2a\u88c5\u90e8\u5206\u5931\u8d25\u3002",
        "smart_spoof_partial_dates_failed": "\u65e5\u671f\u4f2a\u88c5\u90e8\u5206\u5931\u8d25\u3002",
        "smart_spoof_partial_author_failed": "\u4f5c\u8005\u4f2a\u88c5\u90e8\u5206\u5931\u8d25\u3002",
        "smart_spoof_partial_software_failed": "\u8f6f\u4ef6\u4f2a\u88c5\u90e8\u5206\u5931\u8d25\u3002",
        "smart_spoof_partial_raw_failed": "RAW \u6807\u8bc6\u4f2a\u88c5\u90e8\u5206\u5931\u8d25\u3002",
        "smart_spoof_partial_region_cleanup_failed": "Region/Face 清理部分失败。",
        "smart_spoof_partial_non_region_cleanup_failed": "敏感标签清理部分失败。",
        "status_clean": "CLEAN",
        "status_removed": "CLEAN",
        "status_risk": "RISK",
        "status_spoofed": "SPOOFED",
        "stays_in": "will stay in",
        "system_date_tooltip": "OS file timestamps \u2014 use randomize or edit to overwrite",
        "unsaved_body": "You have unsaved changes. What would you like to do?",
        "unsaved_cancel": "Cancel",
        "unsaved_discard": "Discard",
        "unsaved_save_first": "Save first",
        "unsaved_title": "Unsaved changes",
        "vintage_mode": "Vintage mode",
        "warning_exiftool_linux": "Install exiftool using your distribution package manager.",
        "warning_exiftool_macos": "Install exiftool: brew install exiftool",
        "warning_exiftool_missing": "exiftool.exe not found - place it in the bin/ folder. Download: exiftool.org",
        "warning_exiftool_windows": "exiftool is included - no action needed.",
        "worker_session_busy": "\u8bf7\u7a0d\u5019\uff0c\u53e6\u4e00\u9879\u64cd\u4f5c\u6b63\u5728\u8fdb\u884c\u3002",
    },
}

GROUP_META: dict[str, tuple[str, str]] = {
    "gps": ("📍", "gps"),
    "device": ("📷", "device"),
    "author_dates": ("✍️", "author_dates"),
    "other": ("📋", "other"),
}


FILE_BADGE_COLORS: dict[str, str] = {
    "jpeg": "#6366f1",
    "jpg": "#6366f1",
    "png": "#22c55e",
    "heic": "#f59e0b",
    "heif": "#f59e0b",
    "pdf": "#ef4444",
    "docx": "#2563eb",
    "mp4": "#a855f7",
    "mov": "#a855f7",
    "tiff": "#14b8a6",
    "webp": "#06b6d4",
    "raw": "#64748b",
}


def status_colors(status: str) -> tuple[str, str, str]:
    s = status.upper()
    if s == "RISK":
        return "rgba(239,68,68,0.12)", "#ef4444", "#fecaca"
    if s == "SPOOFED":
        return "rgba(168,85,247,0.15)", "#a855f7", "#e9d5ff"
    if s in {"CLEAN", "REMOVED"}:
        return "rgba(34,197,94,0.12)", "#22c55e", "#bbf7d0"
    return "rgba(148,163,184,0.12)", "#94a3b8", "#e2e8f0"


def risk_state(count: int, locale: str) -> tuple[str, str]:
    if count <= 0:
        return tr(locale, "risk_clean"), COLORS["success"]
    if count <= 3:
        return f"{count} {tr(locale, 'risk_low')}", COLORS["warning"]
    if count <= 7:
        return f"{count} {tr(locale, 'risk_medium')}", COLORS["warning"]
    return f"{count} {tr(locale, 'risk_high')}", COLORS["danger"]


def tr(locale: str, key: str, **kwargs: object) -> str:
    bucket = LOCALES.get(locale) or LOCALES["en"]
    template = bucket.get(key) or LOCALES["en"].get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template

