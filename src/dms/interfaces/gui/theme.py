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
        "close": "Close",
        "col_actions": "Actions",
        "col_status": "Status",
        "col_tag": "Tag",
        "col_value": "Value",
        "fsdate_accessed_tip": "Filesystem timestamp: when the file was last opened or read. Updates when you view or copy it.",
        "fsdate_created_tip": "Filesystem timestamp: when this copy appeared on disk. A fresh copy shows the current time.",
        "fsdate_modified_tip": "Filesystem timestamp: when the file's contents were last changed. Preserved from the original when copied.",
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
        "batch_overwrite_title": "Overwrite existing files?",
        "batch_overwrite_body": "{n} file(s) already exist in the target folder:\n{files}\n\nOverwrite them?",
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
        "pdf_banner": "PDF: standard cleaning keeps annotation text, form values, attachments, and embedded image metadata.",
        "pdf_clean_title": "PDF Cleaning Options",
        "pdf_clean_body": "Standard cleaning strips document info and annotation authors, while keeping annotation text, form values, and attachments.\n\nChoose optional removals:",
        "pdf_strip_annotations": "Also remove all annotations and comment text",
        "pdf_strip_attachments": "Also remove embedded file attachments",
        "pdf_clean_proceed": "Clean PDF",
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
        "all": "Все",
        "app_title": "DMS",
        "close": "Закрыть",
        "col_actions": "Действия",
        "col_status": "Статус",
        "col_tag": "Тег",
        "col_value": "Значение",
        "fsdate_accessed_tip": "Метка файловой системы: когда файл последний раз открывали или читали. Обновляется при просмотре и копировании.",
        "fsdate_created_tip": "Метка файловой системы: когда эта копия появилась на диске. У свежей копии — текущее время.",
        "fsdate_modified_tip": "Метка файловой системы: когда в последний раз менялось содержимое файла. При копировании переносится с оригинала.",
        "applied": "Применено",
        "apply": "Применить",
        "author_dates": "Автор и даты",
        "author_label": "Автор",
        "back": "Назад",
        "batch_add_more": "Добавить файлы",
        "batch_analyzing": "Анализ…",
        "batch_apply": "Запустить",
        "batch_complete": "Готово: {n} файл(ов)",
        "batch_done": "Готово",
        "batch_error": "Ошибка",
        "batch_hint": "Добавьте файлы, выберите режим и запустите.",
        "batch_processing": "Обработка…",
        "batch_processing_btn": "Обработка…",
        "batch_ready": "Готов",
        "batch_save_all": "Выберите папку для сохранения",
        "batch_overwrite_title": "Перезаписать существующие файлы?",
        "batch_overwrite_body": "В папке назначения уже существует {n} файл(ов):\n{files}\n\nПерезаписать их?",
        "batch_title": "Пакетная обработка",
        "batch_waiting": "Ожидание",
        "browse_file": "Обзор",
        "clean_residual_body": "Удалить {n} оставшихся чувствительных тег(ов)?",
        "clean_residual_btn": "Очистить остатки",
        "clean_residual_confirm": "Удалить {n}",
        "clean_residual_nothing": "Остаточных чувствительных тегов не найдено.",
        "clean_residual_title": "Очистка остаточных тегов",
        "clean_residual_toast": "Удалено остаточных тегов: {n}",
        "clear": "Очистить",
        "compare_back": "Назад",
        "compare_btn": "Сравнить",
        "menu_language": "Язык",
        "compare_cleaned": "После",
        "compare_hide_unchanged": "Скрыть без изменений ({n})",
        "compare_injected": "(добавлено)",
        "compare_injected_badge": "НОВОЕ",
        "compare_not_present": "(отсутствует)",
        "compare_original": "До",
        "compare_removed": "(удалено)",
        "compare_save": "Сохранить копию",
        "compare_show_unchanged": "Показать без изменений ({n})",
        "compare_summary": "Удалено: {r}  ·  Изменено: {s}  ·  Без изменений: {u}",
        "compare_title": "Сравнение метаданных",
        "computed_tooltip": "Это поле вычисляется exiftool и не может быть удалено напрямую",
        "date_readonly_warning": "Эта дата управляется ОС — используйте случайную дату или редактор дат.",
        "dates_label": "Даты",
        "detected": "Найдено",
        "device": "Устройство",
        "device_label": "Устройство",
        "dms_output_add": "Всё равно добавить",
        "dms_output_body": "Некоторые файлы похожи на ранее обработанные в DMS. Добавить их всё равно?",
        "dms_output_cancel": "Отмена",
        "dms_output_skip": "Пропустить похожие",
        "dms_output_title": "Обнаружен прошлый экспорт",
        "drop_formats": "JPG PNG HEIC TIFF WebP RAW PDF DOCX MP4",
        "drop_subtitle": "Перетащите файл, чтобы увидеть скрытые данные",
        "edit": "Изменить:",
        "field_removed": "Поле удалено",
        "full_title": "Deceptive Metadata Shredder",
        "gps": "GPS и локация",
        "gps_label": "Координаты GPS",
        "gps_spoofed": "GPS успешно подменён",
        "important": "Важные",
        "keep": "Оставить",
        "loading": "Обработка…",
        "mode_remove": "Удалить метаданные",
        "mode_spoof": "Умная подмена",
        "mode_spoof_clean": "Подмена и очистка",
        "other": "Прочее",
        "pdf_banner": "PDF: обычная очистка сохраняет текст аннотаций, значения форм, вложения и метаданные встроенных изображений.",
        "pdf_clean_title": "Параметры очистки PDF",
        "pdf_clean_body": "Обычная очистка удаляет сведения о документе и авторов аннотаций, сохраняя текст аннотаций, поля форм и вложения.\n\nДополнительно удалить:",
        "pdf_strip_annotations": "Также удалить все аннотации и текст комментариев",
        "pdf_strip_attachments": "Также удалить встроенные файлы-вложения",
        "pdf_clean_proceed": "Очистить PDF",
        "progress_author": "Подмена автора…",
        "progress_dates": "Подмена дат…",
        "progress_device": "Подмена устройства…",
        "progress_gps": "Умная подмена…",
        "random": "Случайно",
        "raw_banner": "RAW: часть встроенных тегов может сохраниться — для полного контроля используйте DNG.",
        "raw_tip": "Совет: конвертируйте в DNG для полного контроля над метаданными.",
        "raw_warning_body": "Файлы RAW могут сохранять часть встроенных метаданных. Продолжить?",
        "raw_warning_cancel": "Отмена",
        "raw_warning_proceed": "Продолжить",
        "raw_warning_title": "Файл RAW",
        "region_tooltip": "Находится в блоке Apple XMP — будет удалено при полной очистке областей",
        "remove": "Удалить",
        "remove_all": "Удалить всё",
        "risk_clean": "Чисто",
        "risk_high": "Высокий риск",
        "risk_low": "Низкий риск",
        "risk_medium": "Средний риск",
        "save_copy": "Сохранить копию",
        "save_dialog_title": "Сохранить очищенную копию",
        "saved_to": "Файл сохранён: {path}",
        "saved_toast": "Сохранено: {filename}",
        "sensitive": "чувствит.",
        "shift": "Сдвиг",
        "smart_spoof": "Умная подмена",
        "smart_spoof_skip_gps_no_source": "GPS пропущен — в файле нет пары широта/долгота.",
        "smart_spoof_skip_gps_no_country_data": "GPS пропущен — не найден countries.geojson.",
        "smart_spoof_skip_device_no_candidates": "Подмена устройства пропущена — нет доступных моделей для замены.",
        "smart_spoof_partial_gps_failed": "Подмена GPS выполнена частично.",
        "smart_spoof_partial_device_failed": "Подмена устройства выполнена частично.",
        "smart_spoof_partial_dates_failed": "Подмена дат выполнена частично.",
        "smart_spoof_partial_author_failed": "Подмена автора выполнена частично.",
        "smart_spoof_partial_software_failed": "Подмена ПО выполнена частично.",
        "smart_spoof_partial_raw_failed": "Подмена RAW-идентификаторов выполнена частично.",
        "smart_spoof_partial_region_cleanup_failed": "Очистка Region/FaceID выполнена частично.",
        "smart_spoof_partial_non_region_cleanup_failed": "Очистка чувствительных тегов выполнена частично.",
        "status_clean": "ЧИСТО",
        "status_removed": "ЧИСТО",
        "status_risk": "РИСК",
        "status_spoofed": "ПОДМЕНА",
        "stays_in": "останется в",
        "system_date_tooltip": "Временные метки ОС — используйте случайную дату или редактор",
        "unsaved_body": "Есть несохранённые изменения. Что сделать?",
        "unsaved_cancel": "Отмена",
        "unsaved_discard": "Не сохранять",
        "unsaved_save_first": "Сначала сохранить",
        "unsaved_title": "Несохранённые изменения",
        "vintage_mode": "Ретро-режим",
        "warning_exiftool_linux": "Установите exiftool через менеджер пакетов вашего дистрибутива.",
        "warning_exiftool_macos": "Установите exiftool: brew install exiftool",
        "warning_exiftool_missing": "exiftool.exe не найден — поместите его в папку bin/. Скачать: exiftool.org",
        "warning_exiftool_windows": "exiftool уже встроен — установка не требуется.",
        "worker_session_busy": "Подождите — выполняется другая операция.",
    },
    "zh": {
        "all": "全部",
        "app_title": "DMS",
        "close": "关闭",
        "col_actions": "操作",
        "col_status": "状态",
        "col_tag": "标签",
        "col_value": "值",
        "fsdate_accessed_tip": "文件系统时间戳：文件最后一次打开或读取的时间。查看或复制时会更新。",
        "fsdate_created_tip": "文件系统时间戳：此副本在磁盘上出现的时间。新副本显示当前时间。",
        "fsdate_modified_tip": "文件系统时间戳：文件内容最后一次更改的时间。复制时会保留原始值。",
        "applied": "已应用",
        "apply": "应用",
        "author_dates": "作者与日期",
        "author_label": "作者",
        "back": "返回",
        "batch_add_more": "添加更多文件",
        "batch_analyzing": "正在分析…",
        "batch_apply": "开始批处理",
        "batch_complete": "批处理完成：{n} 个文件",
        "batch_done": "完成",
        "batch_error": "错误",
        "batch_hint": "添加文件，选择模式，然后运行。",
        "batch_processing": "处理中…",
        "batch_processing_btn": "处理中…",
        "batch_ready": "就绪",
        "batch_save_all": "选择输出文件夹",
        "batch_overwrite_title": "覆盖现有文件？",
        "batch_overwrite_body": "目标文件夹中已存在 {n} 个文件：\n{files}\n\n是否覆盖？",
        "batch_title": "批处理",
        "batch_waiting": "等待中",
        "browse_file": "浏览",
        "clean_residual_body": "移除剩余的 {n} 个敏感标签？",
        "clean_residual_btn": "清理残留",
        "clean_residual_confirm": "移除 {n} 项",
        "clean_residual_nothing": "未发现残留敏感标签。",
        "clean_residual_title": "清理残留标签",
        "clean_residual_toast": "已清理 {n} 个残留标签",
        "clear": "清除",
        "compare_back": "返回",
        "compare_btn": "对比",
        "menu_language": "语言",
        "compare_cleaned": "处理后",
        "compare_hide_unchanged": "隐藏未更改项 ({n})",
        "compare_injected": "(已新增)",
        "compare_injected_badge": "新增",
        "compare_not_present": "(不存在)",
        "compare_original": "原始",
        "compare_removed": "(已移除)",
        "compare_save": "保存副本",
        "compare_show_unchanged": "显示未更改项 ({n})",
        "compare_summary": "已移除: {r}  ·  已修改: {s}  ·  未更改: {u}",
        "compare_title": "元数据对比",
        "computed_tooltip": "此字段由 exiftool 自动计算，无法直接删除",
        "date_readonly_warning": "此日期由操作系统管理 — 请使用随机化或日期编辑器。",
        "dates_label": "日期",
        "detected": "已检测",
        "device": "设备",
        "device_label": "设备",
        "dms_output_add": "仍然添加",
        "dms_output_body": "部分文件看起来像先前 DMS 导出的文件，是否仍要添加？",
        "dms_output_cancel": "取消",
        "dms_output_skip": "跳过相似文件",
        "dms_output_title": "检测到先前导出文件",
        "drop_formats": "JPG PNG HEIC TIFF WebP RAW PDF DOCX MP4",
        "drop_subtitle": "拖入文件以查看隐藏数据",
        "edit": "编辑：",
        "field_removed": "字段已移除",
        "full_title": "Deceptive Metadata Shredder",
        "gps": "GPS 与位置",
        "gps_label": "GPS 位置",
        "gps_spoofed": "GPS 伪装成功",
        "important": "重要",
        "keep": "保留",
        "loading": "处理中…",
        "mode_remove": "移除元数据",
        "mode_spoof": "智能伪装",
        "mode_spoof_clean": "先伪装后清理",
        "other": "其他",
        "pdf_banner": "PDF：标准清理会保留批注文本、表单值、附件和嵌入图片的元数据。",
        "pdf_clean_title": "PDF 清理选项",
        "pdf_clean_body": "标准清理会删除文档信息和批注作者，但保留批注文本、表单值和附件。\n\n选择额外移除项：",
        "pdf_strip_annotations": "同时删除所有批注和评论文本",
        "pdf_strip_attachments": "同时删除嵌入的附件文件",
        "pdf_clean_proceed": "清理 PDF",
        "progress_author": "正在伪装作者…",
        "progress_dates": "正在伪装日期…",
        "progress_device": "正在伪装设备…",
        "progress_gps": "正在智能伪装…",
        "random": "随机",
        "raw_banner": "RAW：部分嵌入标签可能保留 — 建议使用 DNG 以获得完全控制。",
        "raw_tip": "提示：转换为 DNG 可获得最大的元数据控制能力。",
        "raw_warning_body": "RAW 格式可能会保留部分嵌入元数据，是否继续？",
        "raw_warning_cancel": "取消",
        "raw_warning_proceed": "继续",
        "raw_warning_title": "RAW 文件",
        "region_tooltip": "位于 Apple XMP 块中 — 将随区域清理一同移除",
        "remove": "移除",
        "remove_all": "全部删除",
        "risk_clean": "安全",
        "risk_high": "高风险",
        "risk_low": "低风险",
        "risk_medium": "中等风险",
        "save_copy": "保存副本",
        "save_dialog_title": "保存已清理副本",
        "saved_to": "文件已保存至：{path}",
        "saved_toast": "已保存 {filename}",
        "sensitive": "敏感项",
        "shift": "偏移",
        "smart_spoof": "智能伪装",
        "smart_spoof_skip_gps_no_source": "已跳过 GPS — 文件中无有效的经纬度对。",
        "smart_spoof_skip_gps_no_country_data": "已跳过 GPS 伪装 — 未找到 countries.geojson。",
        "smart_spoof_skip_device_no_candidates": "已跳过设备伪装 — 没有可用的替代设备。",
        "smart_spoof_partial_gps_failed": "GPS 伪装部分失败。",
        "smart_spoof_partial_device_failed": "设备伪装部分失败。",
        "smart_spoof_partial_dates_failed": "日期伪装部分失败。",
        "smart_spoof_partial_author_failed": "作者伪装部分失败。",
        "smart_spoof_partial_software_failed": "软件伪装部分失败。",
        "smart_spoof_partial_raw_failed": "RAW 标识伪装部分失败。",
        "smart_spoof_partial_region_cleanup_failed": "Region/Face 清理部分失败。",
        "smart_spoof_partial_non_region_cleanup_failed": "敏感标签清理部分失败。",
        "status_clean": "安全",
        "status_removed": "安全",
        "status_risk": "风险",
        "status_spoofed": "已伪装",
        "stays_in": "将保留在",
        "system_date_tooltip": "系统文件时间戳 — 可使用随机化或编辑器覆盖",
        "unsaved_body": "您有未保存的更改，想要如何处理？",
        "unsaved_cancel": "取消",
        "unsaved_discard": "放弃更改",
        "unsaved_save_first": "先保存",
        "unsaved_title": "未保存的更改",
        "vintage_mode": "复古模式",
        "warning_exiftool_linux": "请使用发行版的包管理器安装 exiftool。",
        "warning_exiftool_macos": "安装 exiftool：brew install exiftool",
        "warning_exiftool_missing": "未找到 exiftool.exe — 请将其放入 bin/ 文件夹。下载：exiftool.org",
        "warning_exiftool_windows": "已内置 exiftool — 无需额外操作。",
        "worker_session_busy": "请稍候，另一项操作正在进行。",
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

