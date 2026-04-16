"""Human-friendly error messages for UI surfaces."""

from __future__ import annotations


ERROR_MESSAGES = {
    "en": {
        "cannot_delete_system_field": "This field is managed by the OS and cannot be removed.",
        "cannot_write_field": "This field is read-only and cannot be modified.",
        "exiftool_not_found": "exiftool not found. Place exiftool.exe in the bin/ folder.",
        "exiftool_failed": "Could not process the file. It may be corrupted or unsupported.",
        "gps_no_data": "No GPS data found in this file.",
        "gps_country_unknown": "Could not determine country. GPS will be set to a random ocean point.",
        "gps_invalid_coords": "Invalid coordinates. Please enter valid latitude and longitude.",
        "file_not_found": "File not found. It may have been moved or deleted.",
        "file_permission": "Cannot write to this file. Check that it is not open in another app.",
        "file_corrupted": "This file appears to be corrupted and cannot be processed.",
        "file_unsupported": "This file format is not supported.",
        "file_save_failed": "Could not save the file. Check available disk space.",
        "spoof_nothing_to_do": "Nothing to spoof — no sensitive fields found in this file.",
        "spoof_partial": "Some fields could not be spoofed (read-only or computed).",
        "spoof_device_failed": "Could not apply device profile. Fields may be read-only.",
        "missing_argument": "An internal error occurred. Please try again.",
        "unexpected_error": "Something went wrong. Please try again.",
        "batch_file_failed": "Could not process {filename}. Skipping.",
    },
    "ru": {
        "cannot_delete_system_field": "Это поле управляется операционной системой и не может быть удалено.",
        "cannot_write_field": "Это поле только для чтения и не может быть изменено.",
        "exiftool_not_found": "exiftool не найден. Поместите exiftool.exe в папку bin/.",
        "exiftool_failed": "Не удалось обработать файл. Возможно, он повреждён или не поддерживается.",
        "gps_no_data": "GPS данные в этом файле не найдены.",
        "gps_country_unknown": "Не удалось определить страну. GPS будет заменён на случайную точку в океане.",
        "gps_invalid_coords": "Неверные координаты. Введите корректные широту и долготу.",
        "file_not_found": "Файл не найден. Возможно, он был перемещён или удалён.",
        "file_permission": "Нет доступа к файлу. Убедитесь, что он не открыт в другом приложении.",
        "file_corrupted": "Файл повреждён и не может быть обработан.",
        "file_unsupported": "Этот формат файла не поддерживается.",
        "file_save_failed": "Не удалось сохранить файл. Проверьте свободное место на диске.",
        "spoof_nothing_to_do": "Нечего подменять — в файле не найдено чувствительных данных.",
        "spoof_partial": "Некоторые поля не удалось подменить (только для чтения или вычисляемые).",
        "spoof_device_failed": "Не удалось применить профиль устройства. Поля могут быть защищены.",
        "missing_argument": "Произошла внутренняя ошибка. Попробуйте ещё раз.",
        "unexpected_error": "Что-то пошло не так. Попробуйте ещё раз.",
        "batch_file_failed": "Не удалось обработать {filename}. Файл пропущен.",
    },
    "zh": {
        "cannot_delete_system_field": "此字段由操作系统管理，无法删除。",
        "cannot_write_field": "此字段为只读，无法修改。",
        "exiftool_not_found": "未找到 exiftool。请将 exiftool.exe 放入 bin/ 文件夹。",
        "exiftool_failed": "无法处理此文件，可能已损坏或不受支持。",
        "gps_no_data": "此文件中未找到 GPS 数据。",
        "gps_country_unknown": "无法确定国家，GPS 将被替换为随机海洋坐标。",
        "gps_invalid_coords": "坐标无效，请输入正确的经纬度。",
        "file_not_found": "文件未找到，可能已被移动或删除。",
        "file_permission": "无法写入文件，请确认文件未在其他应用中打开。",
        "file_corrupted": "文件已损坏，无法处理。",
        "file_unsupported": "不支持此文件格式。",
        "file_save_failed": "无法保存文件，请检查磁盘空间。",
        "spoof_nothing_to_do": "无需替换——此文件中未找到敏感字段。",
        "spoof_partial": "部分字段无法替换（只读或计算字段）。",
        "spoof_device_failed": "无法应用设备配置文件，字段可能受保护。",
        "missing_argument": "发生内部错误，请重试。",
        "unexpected_error": "出现问题，请重试。",
        "batch_file_failed": "无法处理 {filename}，已跳过。",
    },
}


def get_error(key: str, lang: str = "en", **kwargs) -> str:
    """Return a localized, user-facing error string."""

    message = ERROR_MESSAGES.get(lang, ERROR_MESSAGES["en"]).get(key, ERROR_MESSAGES["en"].get(key, key))
    return message.format(**kwargs)


def classify_exiftool_error(stderr: str, lang: str = "en") -> str:
    """Map raw exiftool stderr to a human-readable message."""

    text = stderr or ""
    lowered = text.lower()
    if "Nothing to do" in text or "nothing to do" in lowered:
        return get_error("cannot_delete_system_field", lang)
    if "File not found" in text:
        return get_error("file_not_found", lang)
    if "Error creating" in text or "permission" in lowered:
        return get_error("file_permission", lang)
    if "Not a valid" in text or "Unknown file type" in text:
        return get_error("file_unsupported", lang)
    if "missing" in lowered and "argument" in lowered:
        return get_error("missing_argument", lang)
    if "read only" in lowered or "read-only" in lowered or "writable" in lowered:
        return get_error("cannot_write_field", lang)
    return get_error("exiftool_failed", lang)
