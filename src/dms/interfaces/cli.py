"""Rich-powered command line interface."""

from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text
from watchdog.observers import Observer

from dms import __version__
from dms.config import require_exiftool
from dms.core import analyzer
from dms.core.device_db import get_all_devices, get_all_makes, get_models_by_make, get_random_device, get_random_vintage
from dms.core.error_messages import classify_exiftool_error, get_error
from dms.core.exiftool_tags import validate_exif_tag
from dms.core.models import FileReport, MetaField, SpoofProfile, parse_metadata_datetime
from dms.core.sanitizer import OutputPathError, build_output_path, remove_all
from dms.core.spoofer import (
    _existing_author_fields,
    _find_gps_field,
    apply_smart_spoof,
    apply_spoof,
    set_filesystem_dates,
)
from dms.core.utils import EXIFTOOL_TEXT_KWARGS, EXIFTOOL_TIMEOUT, get_subprocess_flags, remove_exiftool_signature
from dms.interfaces.watcher import DMSEventHandler


def _enable_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_enable_utf8_console()
console = Console()
app = typer.Typer(
    help=(
        "Deceptive Metadata Shredder (DMS): offline inspection, removal, and spoofing of metadata "
        "in photos, PDFs, Office docs, and video. Use each subcommand with --help for flags."
    ),
    no_args_is_help=False,
    pretty_exceptions_enable=False,
)

BANNER = """██████╗ ███╗   ███╗███████╗
██╔══██╗████╗ ████║██╔════╝
██║  ██║██╔████╔██║███████╗
██║  ██║██║╚██╔╝██║╚════██║
██████╔╝██║ ╚═╝ ██║███████║
╚═════╝ ╚═╝     ╚═╝╚══════╝"""

ASCII_FALLBACK_BANNER = """DMS
=============================="""

CATEGORY_TITLES = {
    "gps": "GPS & Location",
    "device": "Device",
    "author": "Author",
    "dates": "Dates",
    "other": "Other",
}

CLI_INFO_MESSAGES = {
    "smart_spoof_skip_gps_no_source": "GPS spoof skipped: no valid latitude/longitude pair in file.",
    "smart_spoof_skip_gps_no_country_data": "GPS spoof skipped: countries.geojson was not found.",
    "smart_spoof_skip_device_no_candidates": "Device spoof skipped: no replacement devices were available.",
    "smart_spoof_partial_gps_failed": "GPS spoof partially failed.",
    "smart_spoof_partial_device_failed": "Device spoof partially failed.",
    "smart_spoof_partial_dates_failed": "Date spoof partially failed.",
    "smart_spoof_partial_author_failed": "Author spoof partially failed.",
    "smart_spoof_partial_software_failed": "Software spoof partially failed.",
    "smart_spoof_partial_raw_failed": "RAW identifier spoof partially failed.",
    "smart_spoof_partial_region_cleanup_failed": "Region/Face cleanup partially failed.",
    "smart_spoof_partial_non_region_cleanup_failed": "Sensitive tag cleanup partially failed.",
}


def configure_logging() -> None:
    """Write technical errors to a writable log file."""

    log_path = Path.cwd() / "dms_errors.log"
    try:
        log_path.touch(exist_ok=True)
    except OSError:
        log_path = Path(tempfile.gettempdir()) / "dms_errors.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.ERROR,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )


def print_banner() -> None:
    """Render the DMS banner."""

    gradient = ["#8b5cf6", "#7c3aed", "#6366f1", "#4f46e5", "#6366f1", "#8b5cf6"]
    text = Text()
    for color, line in zip(gradient, BANNER.splitlines(), strict=True):
        text.append(line + "\n", style=f"bold {color}")
    text.append(f"Deceptive Metadata Shredder v{get_app_version()}\n", style="dim white")
    text.append("Privacy-first metadata tool", style="dim white")
    try:
        console.print(Panel.fit(text, border_style="bright_cyan", box=box.ROUNDED))
    except UnicodeEncodeError:
        fallback = Text()
        fallback.append(ASCII_FALLBACK_BANNER + "\n", style="bold bright_cyan")
        fallback.append(f"Deceptive Metadata Shredder v{get_app_version()}\n", style="dim white")
        fallback.append("Privacy-first metadata tool", style="dim white")
        console.print(Panel.fit(fallback, border_style="bright_cyan", box=box.SQUARE))


def get_app_version() -> str:
    """Return the application version."""

    return __version__


def get_exiftool_version() -> str:
    """Return the detected exiftool version."""

    try:
        exiftool = analyzer.find_exiftool()
        result = subprocess.run(
            [exiftool, "-ver"],
            capture_output=True,
            check=False,
            timeout=EXIFTOOL_TIMEOUT,
            creationflags=get_subprocess_flags(),
            **EXIFTOOL_TEXT_KWARGS,
        )
        version = (result.stdout or "").strip()
        return version or "not found"
    except Exception:
        return "not found"


def print_error(message: str, *, details: str | None = None) -> None:
    """Show a friendly Rich error."""

    body = Text()
    body.append("✗ Error: ", style="bold red")
    body.append(message, style="bold bright_white")
    if details:
        body.append(f"\n{details}", style="dim white")
    console.print(Panel.fit(body, border_style="red", box=box.ROUNDED))


def handle_exception(exc: Exception) -> None:
    """Convert exceptions to friendly CLI output."""

    logging.error("CLI error: %s", exc, exc_info=True)
    if isinstance(exc, FileNotFoundError):
        print_error(get_error("file_not_found", "en"))
        raise typer.Exit(1)
    if isinstance(exc, PermissionError):
        print_error(get_error("file_permission", "en"))
        raise typer.Exit(1)
    if isinstance(exc, OutputPathError):
        print_error(str(exc))
        raise typer.Exit(1)
    if isinstance(exc, (typer.BadParameter, ValueError)):
        print_error(str(exc))
        raise typer.Exit(2)
    if isinstance(exc, RuntimeError):
        message = classify_exiftool_error(str(exc), "en")
        if "exiftool" in str(exc).lower():
            print_error(
                get_error("exiftool_not_found", "en"),
                details="Install it: https://exiftool.org\nOr place exiftool.exe in the local bin/ folder.",
            )
        else:
            print_error(message)
        raise typer.Exit(1)
    print_error(get_error("unexpected_error", "en"))
    raise typer.Exit(1)


def _ensure_supported(file: Path) -> None:
    if file.suffix.lower() in analyzer.SUPPORTED_FORMATS:
        return
    supported = ", ".join(sorted(analyzer.SUPPORTED_FORMATS))
    console.print(f"[red]Unsupported format: {file.suffix or '[no extension]'}[/red]")
    console.print(f"[dim white]Supported: {supported}[/dim white]")
    raise typer.Exit(code=1)


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def _risk_state(count: int) -> tuple[str, str]:
    if count <= 0:
        return "Clean", "bold green"
    if count <= 3:
        return "Low Risk", "bold yellow"
    if count <= 7:
        return "Medium Risk", "bold #f97316"
    return "High Risk", "bold red"


def _risk_icon(field: MetaField) -> Text:
    if field.status == "spoofed":
        return Text("SPOOFED", style="bold bright_magenta")
    if field.status in {"clean", "removed"}:
        return Text("CLEAN", style="bold green")
    if field.is_sensitive:
        return Text("RISK", style="bold red")
    return Text("INFO", style="bold yellow")


def _field_value(value: Any) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    return text if len(text) <= 80 else f"{text[:77]}..."


def _canonical_key(value: str) -> str:
    return "".join(char.lower() for char in str(value) if char.isalnum())


def _field_aliases(field: MetaField) -> set[str]:
    aliases = {
        _canonical_key(field.key),
        _canonical_key(field.label),
        _canonical_key(field.exiftool_tag),
        _canonical_key(field.exiftool_tag.split(":")[-1]),
        _canonical_key(field.exiftool_tag.split(".")[-1]),
    }
    return {item for item in aliases if item}


def _matches_field_keys(field: MetaField, keys: set[str]) -> bool:
    if not keys:
        return False
    qualified = {_canonical_key(key) for key in keys if ":" in key}
    unqualified = {_canonical_key(key) for key in keys if ":" not in key}
    if qualified and _canonical_key(field.exiftool_tag) in qualified:
        return True
    if unqualified and (_field_aliases(field) & unqualified):
        return True
    return False


def _apply_cli_statuses(report: FileReport, spoofed_keys: set[str] | None = None, removed_keys: set[str] | None = None) -> None:
    spoofed = set(spoofed_keys or set())
    removed = set(removed_keys or set())
    for field in report.fields:
        if _matches_field_keys(field, removed):
            field.status = "removed"
        elif _matches_field_keys(field, spoofed):
            field.status = "spoofed"
        else:
            field.status = "risk" if field.is_sensitive else "clean"


def _report_diff(before: FileReport, after: FileReport) -> tuple[set[str], set[str]]:
    """Return field tags that actually changed and tags that disappeared."""

    after_values: dict[str, set[str]] = {}
    for field in after.fields:
        tag_id = (field.exiftool_tag or field.key).lower()
        after_values.setdefault(tag_id, set()).add(str(field.value))
    before_tags = {(field.exiftool_tag or field.key).lower() for field in before.fields}

    changed: set[str] = set()
    removed: set[str] = set()
    for field in before.fields:
        if field.is_computed or not field.is_sensitive or field.key in analyzer.FILESYSTEM_DATE_KEYS:
            continue
        tag = field.exiftool_tag or field.key
        values = after_values.get(tag.lower())
        if values is None:
            removed.add(tag)
        elif str(field.value) not in values:
            changed.add(tag)
    for field in after.fields:
        tag = field.exiftool_tag or field.key
        if (
            tag.lower() not in before_tags
            and not field.is_computed
            and field.is_sensitive
            and field.key not in analyzer.FILESYSTEM_DATE_KEYS
        ):
            changed.add(tag)
    return changed, removed


def _effective_category(field: MetaField) -> str:
    if field.category == "gps" or field.key.startswith("GPS"):
        return "gps"
    return field.category


def _changed_categories(before: FileReport, after: FileReport, keys: set[str]) -> list[str]:
    order = ["gps", "device", "author", "dates", "other"]
    present = {
        _effective_category(field)
        for report in (before, after)
        for field in report.fields
        if _matches_field_keys(field, keys)
    }
    return [category for category in order if category in present]


def _risk_count(report: FileReport) -> int:
    return sum(
        1
        for field in report.fields
        if field.status == "risk" and field.key not in analyzer.FILESYSTEM_DATE_KEYS
    )


def _serialize_report(report: FileReport) -> dict[str, Any]:
    risk_count = _risk_count(report)
    if report.analysis_status != "ok":
        status = "unverified"
    elif risk_count:
        status = "dirty"
    else:
        status = "clean"
    return {
        "path": str(report.path),
        "file_type": report.file_type,
        "status": status,
        "analysis_status": report.analysis_status,
        "analysis_error": report.analysis_error,
        "warnings": report.warnings,
        "empty_reason": report.empty_reason,
        "fields": [
            {
                "exiftool_tag": field.exiftool_tag,
                "key": field.key,
                "label": field.label,
                "value": field.value,
                "category": field.category,
                "is_sensitive": field.is_sensitive,
                "is_computed": field.is_computed,
                "status": field.status,
            }
            for field in report.fields
        ],
    }


def _group_fields(report: FileReport) -> list[tuple[str, list[MetaField]]]:
    order = ["gps", "device", "author", "dates", "other"]
    groups: list[tuple[str, list[MetaField]]] = []
    for key in order:
        fields = [field for field in report.fields if field.category == key]
        if fields:
            groups.append((CATEGORY_TITLES.get(key, key.title()), fields))
    return groups


def _report_header(report: FileReport) -> Panel:
    risk_count = _risk_count(report)
    risk_label, risk_style = _risk_state(risk_count)
    header = Text()
    header.append(f"Size: {_format_bytes(report.path.stat().st_size)}    ", style="dim white")
    header.append(f"Type: {report.file_type.upper()}    ", style="bright_cyan")
    header.append("Risk: ", style="dim white")
    header.append(f"{risk_label.upper()} ({risk_count} fields)", style=risk_style)
    return Panel.fit(header, title=report.path.name, border_style="bright_cyan", box=box.ROUNDED)


def _render_analysis_table(report: FileReport) -> None:
    console.print(_report_header(report))
    console.print(f"[dim white]Supported formats:[/dim white] {' '.join(analyzer.supported_format_labels())}")
    for title, fields in _group_fields(report):
        console.print(Text(f"\n{title}", style="bold bright_white"))
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold bright_white")
        table.add_column("Tag", style="bright_cyan", overflow="fold")
        table.add_column("Value", style="white", overflow="fold")
        table.add_column("Risk", justify="center", width=12)
        for field in fields:
            table.add_row(field.label, _field_value(field.value), _risk_icon(field))
        console.print(table)
    sensitive = _risk_count(report)
    categories = len(
        [
            1
            for _, fields in _group_fields(report)
            if any(field.status == "risk" and field.key not in analyzer.FILESYSTEM_DATE_KEYS for field in fields)
        ]
    )
    console.print(f"[bold bright_white]Summary:[/bold bright_white] {sensitive} sensitive fields found across {categories} categories.")


def _render_minimal(report: FileReport) -> None:
    for field in report.fields:
        console.print(f"{field.exiftool_tag}={_field_value(field.value)}")


def _command_summary() -> Table:
    table = Table(box=box.ROUNDED, header_style="bold bright_white")
    table.add_column("Command", style="bright_cyan")
    table.add_column("What it does", style="white")
    table.add_row("dms analyze <file>", "Show all fields and highlight sensitive metadata")
    table.add_row("dms verify <file>", "Check whether a file still holds sensitive metadata")
    table.add_row("dms clean <file>", "Write a copy with metadata stripped (*_cleaned by default)")
    table.add_row("dms spoof <file>", "Replace GPS/device/dates/author with plausible values")
    table.add_row("dms devices", "List available device IDs for --device")
    table.add_row("dms watch <folder>", "React to new files in a folder (optional dms_cleaned/ output)")
    table.add_row("dms batch <paths…>", "Clean or spoof many files at once (--output-dir optional)")
    return table


def _confirm(message: str, *, yes: bool) -> bool:
    if yes:
        return True
    return typer.confirm(message, default=False)


def _parse_gps_argument(value: str) -> tuple[str, tuple[float, float] | None]:
    lowered = value.lower().strip()
    if lowered in {"smart", "remove"}:
        return lowered, None
    if "," in value:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            raise typer.BadParameter("Invalid GPS coordinates. Use smart, remove, or lat,lon.")
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise typer.BadParameter("Invalid GPS coordinates. Latitude and longitude must be numbers.") from exc
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise typer.BadParameter("GPS coordinates out of range (lat: -90..90, lon: -180..180).")
        return "manual", (lat, lon)
    raise typer.BadParameter("Use smart, remove, or lat,lon.")


def _parse_dates_argument(value: str) -> tuple[str, int]:
    lowered = value.lower().strip()
    if lowered in {"random", "remove", "keep"}:
        return lowered, 0
    if lowered.startswith("shift:"):
        try:
            return "shift", int(lowered.split(":", 1)[1])
        except ValueError as exc:
            raise typer.BadParameter("Invalid shift offset. Use shift:<days> with an integer.") from exc
    raise typer.BadParameter("Use random, remove, keep, or shift:<days>.")


def _resolve_device_option(option: str) -> tuple[str | None, str | None]:
    lowered = option.lower()
    if lowered == "random":
        device = get_random_device()
        return device.make, device.model
    if lowered == "vintage":
        device = get_random_vintage()
        return device.make, device.model
    for make in get_all_makes():
        match = next((item for item in get_models_by_make(make) if item.id == option), None)
        if match:
            return match.make, match.model
    raise typer.BadParameter(f"Unknown device id: {option}. Run 'dms devices' to list available IDs.")


def _default_spoof_output(path: Path, output: Path | None) -> Path:
    return output or path.with_name(f"{path.stem}_spoofed{path.suffix}")


def _same_file(first: Path, second: Path) -> bool:
    try:
        if first.resolve() == second.resolve():
            return True
        return second.exists() and first.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def _ensure_output_differs(source: Path, target: Path) -> None:
    if _same_file(source, target):
        raise OutputPathError("Output path must differ from the source file. DMS never overwrites the original.")


def _confirm_overwrite(target: Path, *, yes: bool) -> None:
    if target.exists() and not _confirm(f"{target} already exists. Overwrite?", yes=yes):
        raise typer.Exit(1)


def _preview_spoof_plan(report: FileReport, profile: SpoofProfile, smart: bool) -> tuple[Table, list[str]]:
    table = Table(box=box.ROUNDED, header_style="bold bright_white")
    table.add_column("Field", style="bright_cyan")
    table.add_column("Original", style="white", overflow="fold")
    table.add_column("Will become", style="bold bright_magenta", overflow="fold")
    changes: list[str] = []

    fields = report.by_key()
    gps_lat = fields.get("GPSLatitude")
    gps_lon = fields.get("GPSLongitude")
    has_gps_metadata = _find_gps_field(report) is not None
    gps_target_text: str | None = None
    if smart:
        if gps_lat and gps_lon and gps_lat.value not in (None, "") and gps_lon.value not in (None, ""):
            gps_target_text = "~same country (random)"
    elif has_gps_metadata:
        if profile.gps_mode == "remove":
            gps_target_text = "removed"
        elif profile.gps_mode == "manual" and profile.gps_target:
            gps_target_text = str(profile.gps_target)
        elif profile.gps_mode == "smart":
            gps_target_text = "~same country (random)"
    if gps_target_text is not None:
        original = (
            f"{gps_lat.value}, {gps_lon.value}"
            if gps_lat and gps_lon and gps_lat.value not in (None, "") and gps_lon.value not in (None, "")
            else "—"
        )
        table.add_row("GPS Location", original, gps_target_text)
        changes.append("gps")

    make = fields.get("Make")
    model = fields.get("Model")
    has_make = bool(make and make.value not in (None, ""))
    device_will_change = (
        (smart and has_make)
        or (not smart and bool(profile.device_make and profile.device_model))
    )
    if device_will_change:
        device_text = "random device"
        if profile.device_make and profile.device_model:
            device_text = f"{profile.device_make} {profile.device_model}"
        table.add_row("Device Model", f"{make.value if make else '—'} {model.value if model else ''}".strip(), device_text)
        changes.append("device")

    date_field = next(
        (
            field
            for field in report.fields
            if field.category == "dates"
            and field.key not in analyzer.FILESYSTEM_DATE_KEYS
            and (not smart or field.is_sensitive)
        ),
        None,
    )
    dates_will_change = (smart and date_field is not None) or (not smart and profile.dates_mode != "keep")
    if dates_will_change:
        if smart or profile.dates_mode == "random":
            target = "random past date"
        elif profile.dates_mode == "remove":
            target = "removed"
        elif profile.dates_mode == "shift":
            target = f"shifted by {profile.dates_shift_days} days"
        else:
            target = "kept"
        table.add_row("Create Date", _field_value(date_field.value) if date_field else "—", target)
        changes.append("dates")

    author_fields = _existing_author_fields(report)
    if author_fields and (smart or profile.author is not None):
        if smart:
            target = "random name"
        elif profile.author == "":
            target = "removed"
        else:
            target = str(profile.author)
        table.add_row("Author", _field_value(author_fields[0].value), target)
        changes.append("author")

    return table, changes


def _batch_target(file: Path, output_dir: Path | None, mode: str) -> Path:
    suffix = "spoofed" if mode in {"spoof", "spoof_clean"} else "cleaned"
    name = f"{file.stem}_{suffix}{file.suffix}"
    return output_dir / name if output_dir else file.with_name(name)


def _expand_batch_inputs(files: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for file in files:
        pattern = str(file)
        if any(token in pattern for token in ["*", "?", "["]):
            expanded.extend(Path(match) for match in sorted(glob.glob(pattern, recursive=True)))
        else:
            expanded.append(file)
    return [path for path in expanded if path.exists() and path.is_file()]


def _validate_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"clean", "spoof", "spoof_clean"}:
        raise typer.BadParameter(f"Invalid mode: {mode}. Use 'clean', 'spoof', or 'spoof_clean'.")
    return normalized


def _extract_anchor_date(report: FileReport) -> datetime | None:
    for field in report.fields:
        if field.category == "dates" and field.key not in analyzer.FILESYSTEM_DATE_KEYS:
            parsed = parse_metadata_datetime(field.value)
            if parsed is not None:
                return parsed
    return None


def _remove_residual_fields(
    path: Path,
    fields: list[MetaField],
    *,
    fs_date: datetime | None = None,
) -> int:
    removable = [field for field in fields if not field.is_computed]
    if not removable:
        return 0
    exiftool = require_exiftool()
    args = [exiftool, "-m"]
    applied = 0
    for field in removable:
        try:
            safe = validate_exif_tag(field.exiftool_tag)
        except ValueError:
            logging.warning(
                "Skipping residual field: file=%s key=%s tag=%r",
                path,
                field.key,
                field.exiftool_tag,
            )
            continue
        args.append(f"-{safe}=")
        applied += 1
    if applied == 0:
        return 0
    args.extend(["-overwrite_original", str(path)])
    result = subprocess.run(args, capture_output=True, check=False, timeout=EXIFTOOL_TIMEOUT, creationflags=get_subprocess_flags(), **EXIFTOOL_TEXT_KWARGS)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to remove residual fields.")
    remove_exiftool_signature(path, exiftool)
    if fs_date is not None:
        set_filesystem_dates(path, fs_date)
    return applied


def _residual_fields(report: FileReport, spoofed_keys: set[str]) -> list[MetaField]:
    keys = set(spoofed_keys)
    residual: list[MetaField] = []
    for field in report.fields:
        if not field.is_sensitive or field.is_computed:
            continue
        if _matches_field_keys(field, keys):
            continue
        residual.append(field)
    return residual


def _print_info_codes(info_codes: list[str]) -> None:
    for code in info_codes:
        message = CLI_INFO_MESSAGES.get(code, code)
        console.print(f"[yellow]• {message}[/yellow]")


def _render_verification(path: Path) -> bool:
    try:
        residual = analyzer.verify(path)
    except analyzer.MetadataAnalysisError as exc:
        console.print(f"[bold red]! Verification unavailable:[/bold red] {_field_value(exc)}")
        return False
    if not residual:
        console.print("[bold green]✓ Verified:[/bold green] no sensitive metadata remains.")
        return True
    console.print(f"[bold yellow]! Verification:[/bold yellow] {len(residual)} sensitive field(s) still present:")
    table = Table(box=box.ROUNDED, header_style="bold bright_white")
    table.add_column("Field", style="bright_cyan")
    table.add_column("Value", style="white", overflow="fold")
    for field in residual:
        table.add_row(field.label, _field_value(field.value))
    console.print(table)
    return False


def _process_clean(
    file: Path,
    output: Path | None = None,
    *,
    strip_annotations: bool = False,
    strip_attachments: bool = False,
) -> tuple[Path, int]:
    report = analyzer.analyze(file)
    sensitive = _risk_count(report)
    result = remove_all(
        file,
        output,
        strip_annotations=strip_annotations,
        strip_attachments=strip_attachments,
    )
    return result, sensitive


def _process_spoof(
    file: Path,
    output: Path | None = None,
    *,
    residual: bool = False,
    auto_remove_residual: bool = False,
) -> tuple[Path, list[str], list[str], int, int, int, int]:
    report = analyzer.analyze(file)
    original_risk = _risk_count(report)
    final_path = _default_spoof_output(file, output)
    _ensure_output_differs(file, final_path)
    result, _, info_codes = apply_smart_spoof(report, output_path=final_path)
    reloaded = analyzer.analyze(result)
    changed_keys, removed_keys = _report_diff(report, reloaded)
    _apply_cli_statuses(reloaded, spoofed_keys=changed_keys, removed_keys=removed_keys)
    changes = _changed_categories(report, reloaded, changed_keys | removed_keys)
    changed_fields = len(changed_keys | removed_keys)
    removed_residual = 0
    if residual and auto_remove_residual:
        residual_fields = _residual_fields(reloaded, changed_keys)
        residual_keys = {field.key for field in residual_fields}
        removed_residual = _remove_residual_fields(
            result,
            residual_fields,
            fs_date=_extract_anchor_date(reloaded),
        )
        if removed_residual:
            reloaded = analyzer.analyze(result)
            _apply_cli_statuses(reloaded, spoofed_keys=changed_keys, removed_keys=removed_keys | residual_keys)
    return result, changes, info_codes, changed_fields, removed_residual, original_risk, _risk_count(reloaded)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and runtime info.", is_eager=True),
) -> None:
    configure_logging()
    if version:
        print_banner()
        console.print(f"[bold bright_white]DMS[/bold bright_white] v{get_app_version()}")
        console.print(f"[dim white]Python[/dim white] {sys.version.split()[0]}")
        console.print(f"[dim white]exiftool[/dim white] {get_exiftool_version()}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        print_banner()
        console.print(_command_summary())
        console.print(
            "\n[dim white]Tip:[/dim white] [bold bright_cyan]dms <command> --help[/bold bright_cyan] for options "
            "(try [bold]watch --help[/bold] for folder watching and [bold]batch --help[/bold] for many files)."
        )
        raise typer.Exit()


@app.command()
def analyze(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="File to inspect."),
    format: str = typer.Option("table", "--format", help="Output: table (default), json, or minimal."),
) -> None:
    """Read metadata and list sensitive fields (no changes to the file)."""

    try:
        _ensure_supported(file)
        report = analyzer.analyze(file)
        lowered = format.lower()
        if lowered == "json":
            console.print(
                json.dumps(_serialize_report(report), default=str, ensure_ascii=False),
                soft_wrap=True,
                markup=False,
                highlight=False,
            )
        elif lowered == "minimal":
            _render_minimal(report)
        else:
            print_banner()
            _render_analysis_table(report)
        if report.analysis_status != "ok":
            if lowered != "json":
                console.print(
                    f"[bold yellow]! Analysis incomplete:[/bold yellow] "
                    f"{report.analysis_error or 'metadata could not be read completely.'}"
                )
            raise typer.Exit(1)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def verify(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="File to check."),
) -> None:
    """Check whether a file still contains sensitive metadata (read-only)."""

    try:
        _ensure_supported(file)
        if not _render_verification(file):
            raise typer.Exit(1)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def clean(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source file."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Destination path; default is sibling *_cleaned."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    strip_annotations: bool = typer.Option(
        False,
        "--strip-annotations",
        help="Also remove PDF annotations and comments (text, popups).",
    ),
    strip_attachments: bool = typer.Option(
        False,
        "--strip-attachments",
        help="Also remove PDF embedded file attachments.",
    ),
) -> None:
    """Remove all metadata into a new file (original is left unchanged)."""

    try:
        _ensure_supported(file)
        print_banner()
        report = analyzer.analyze(file)
        sensitive = _risk_count(report)
        if report.analysis_status != "ok":
            console.print(f"[bold yellow]! Warning:[/bold yellow] {report.analysis_error or 'metadata could not be read completely.'}")
        if report.file_type == "pdf":
            for warning in report.warnings:
                console.print(f"[yellow]! {warning}[/yellow]")
        target = build_output_path(file, output)
        _ensure_output_differs(file, target)
        _confirm_overwrite(target, yes=yes)
        console.print(f"Found [bold red]{sensitive}[/bold red] sensitive fields in [bold bright_white]{file.name}[/bold bright_white]")
        if not _confirm("This will remove ALL metadata. Continue?", yes=yes):
            raise typer.Exit()

        with Progress(
            SpinnerColumn(style="bright_cyan"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[bold green]Done[/bold green]"),
            console=console,
        ) as progress:
            task = progress.add_task("Removing metadata...", total=100)
            result = remove_all(
                file,
                target,
                strip_annotations=strip_annotations,
                strip_attachments=strip_attachments,
            )
            progress.update(task, completed=100)

        console.print(f"[dim white]Saved to:[/dim white] {result}")
        if not _render_verification(result):
            raise typer.Exit(1)
        console.print(f"[bold green]✓ Cleaned:[/bold green] {result.name}")
        console.print(f"Removed [bold red]{sensitive}[/bold red] sensitive fields.")
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def spoof(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source file."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Destination path; default is sibling *_spoofed."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    gps: str = typer.Option("smart", "--gps", help="smart, remove, or lat,lon."),
    device: str | None = typer.Option(None, "--device", help="Device id from bundled DB (see 'dms devices'), random, vintage, or omit for smart."),
    author: str | None = typer.Option(None, "--author", help="Author string or 'remove'."),
    dates: str = typer.Option("random", "--dates", help="random, remove, keep, or shift:<days>."),
    residual: bool = typer.Option(False, "--residual", help="Remove remaining sensitive fields after spoofing."),
) -> None:
    """Replace sensitive metadata with plausible values (original unchanged)."""

    try:
        _ensure_supported(file)
        print_banner()
        report = analyzer.analyze(file)
        if report.file_type == "raw":
            console.print("[yellow]RAW file detected.[/yellow]")
            console.print("[dim white]Some proprietary tags cannot be modified.[/dim white]")
        original_risk = _risk_count(report)
        if report.analysis_status != "ok":
            console.print(f"[bold yellow]! Warning:[/bold yellow] {report.analysis_error or 'metadata could not be read completely.'}")
        gps_mode, gps_target = _parse_gps_argument(gps)
        dates_mode, dates_shift_days = _parse_dates_argument(dates)
        profile = SpoofProfile(gps_mode=gps_mode, gps_target=gps_target, dates_mode=dates_mode, dates_shift_days=dates_shift_days)

        smart = device is None and author is None and gps == "smart" and dates == "random"
        if device:
            make, model = _resolve_device_option(device)
            profile.device_make = make
            profile.device_model = model
        if author:
            profile.author = "" if author.strip().lower() == "remove" else author

        final_target = _default_spoof_output(file, output)
        _ensure_output_differs(file, final_target)
        _confirm_overwrite(final_target, yes=yes)

        plan_table, _ = _preview_spoof_plan(report, profile, smart)
        console.print(f"[bold bright_white]Smart Spoof plan for {file.name}:[/bold bright_white]")
        console.print(plan_table)
        if not _confirm("Proceed?", yes=yes):
            raise typer.Exit()

        with Progress(
            SpinnerColumn(style="bright_cyan"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Spoofing metadata...", total=4)
            info_codes: list[str] = []
            if smart:
                result, _, info_codes = apply_smart_spoof(report, output_path=final_target)
                progress.update(task, advance=4)
            else:
                progress.update(task, description="[1/4] Preparing spoof plan...")
                progress.advance(task)
                progress.update(task, description="[2/4] Writing spoofed metadata...")
                result = apply_spoof(report, profile, output_path=final_target)
                progress.advance(task)
                progress.update(task, description="[3/4] Finalizing output...")
                progress.advance(task)
                progress.update(task, description="[4/4] Done")
                progress.advance(task)
            final_path = result

        reloaded = analyzer.analyze(final_path)
        changed_keys, removed_keys = _report_diff(report, reloaded)
        _apply_cli_statuses(reloaded, spoofed_keys=changed_keys, removed_keys=removed_keys)
        changes = _changed_categories(report, reloaded, changed_keys | removed_keys)
        changed_fields = len(changed_keys | removed_keys)
        if reloaded.analysis_status != "ok":
            console.print(f"[bold yellow]! Verification unavailable:[/bold yellow] {reloaded.analysis_error or 'metadata could not be read completely.'}")

        removed_residual = 0
        if residual:
            residual_candidates = _residual_fields(reloaded, changed_keys)
            if residual_candidates:
                residual_table = Table(box=box.ROUNDED, header_style="bold bright_white")
                residual_table.add_column("Field", style="bright_cyan")
                residual_table.add_column("Value", style="white", overflow="fold")
                for field in residual_candidates:
                    residual_table.add_row(field.label, _field_value(field.value))
                console.print(
                    f"After spoofing, [bold yellow]{len(residual_candidates)}[/bold yellow] sensitive fields remain that cannot be spoofed:"
                )
                console.print(residual_table)
                if _confirm("Remove these fields?", yes=yes):
                    removed_residual = _remove_residual_fields(
                        final_path,
                        residual_candidates,
                        fs_date=_extract_anchor_date(reloaded),
                    )
                    reloaded = analyzer.analyze(final_path)
                    _apply_cli_statuses(
                        reloaded,
                        spoofed_keys=changed_keys,
                        removed_keys=removed_keys | {field.exiftool_tag or field.key for field in residual_candidates},
                    )

        final_risk = _risk_count(reloaded)
        console.print(f"[bold bright_magenta]✓ Spoofed:[/bold bright_magenta] {final_path.name}")
        console.print(f"Changed [bold bright_magenta]{len(changes)}[/bold bright_magenta] categories, [bold bright_magenta]{changed_fields}[/bold bright_magenta] fields.")
        if removed_residual:
            console.print(f"[bold green]✓ Removed[/bold green] {removed_residual} residual fields")
        if info_codes:
            _print_info_codes(info_codes)
        console.print(f"[dim white]Saved to:[/dim white] {final_path}")
        console.print(f"Risk reduced: [bold red]{original_risk}[/bold red] → [bold green]{final_risk}[/bold green] fields")
        if changed_fields > 0:
            console.print(
                f"[dim white]Note: {changed_fields} field(s) now hold spoofed values; "
                "'dms verify' checks for fully stripped files.[/dim white]"
            )
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def devices(
    make: str | None = typer.Option(None, "--make", help="Filter devices by manufacturer."),
    format: str = typer.Option("table", "--format", help="Output: table (default) or json."),
) -> None:
    """List available device IDs for --device."""

    try:
        items = get_all_devices()
        if make:
            lowered_make = make.strip().lower()
            items = [item for item in items if item.make.lower() == lowered_make]
        if format.lower() == "json":
            payload = [
                {
                    "id": item.id,
                    "make": item.make,
                    "model": item.model,
                    "year": item.year,
                    "software": item.software,
                }
                for item in items
            ]
            console.print(
                json.dumps(payload, ensure_ascii=False),
                soft_wrap=True,
                markup=False,
                highlight=False,
            )
            return
        print_banner()
        table = Table(box=box.ROUNDED, header_style="bold bright_white")
        table.add_column("ID", style="bright_cyan", overflow="fold")
        table.add_column("Make", style="white")
        table.add_column("Model", style="white")
        table.add_column("Year", justify="right", style="dim white")
        table.add_column("Software", style="dim white", overflow="fold")
        for item in items:
            table.add_row(item.id, item.make, item.model, str(item.year), item.software or "—")
        console.print(table)
        console.print(
            f"[dim white]{len(items)} device(s) available. Use with:[/dim white] "
            "[bold bright_cyan]dms spoof <file> --device <ID>[/bold bright_cyan]"
        )
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def watch(
    folder: Path = typer.Argument(..., help="Folder to watch for newly created files."),
    mode: str = typer.Option(
        "clean",
        "--mode",
        help="clean: strip metadata. spoof: smart spoof (needs exiftool). spoof_clean: spoof + strip residual fields.",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        help="Also watch subfolders for new files.",
    ),
    collect_subfolder: bool = typer.Option(
        False,
        "--collect-subfolder",
        help=(
            "Write results under <folder>/dms_cleaned/ (created if missing) instead of *_cleaned next to each source file."
        ),
    ),
    include_all: bool = typer.Option(
        False,
        "--all",
        help=(
            "Also process files whose names end with _cleaned, _spoofed, or _dms. "
            "Only allowed with --collect-subfolder (outputs stay under dms_cleaned/ so the watcher does not loop). "
            "Paths inside dms_cleaned/ are always ignored."
        ),
    ),
    strip_annotations: bool = typer.Option(
        False,
        "--strip-annotations",
        help="Also remove PDF annotations and comments (text, popups).",
    ),
    strip_attachments: bool = typer.Option(
        False,
        "--strip-attachments",
        help="Also remove PDF embedded file attachments.",
    ),
) -> None:
    """Watch a folder and process new files as they appear (outputs are copies; sources are not edited in place).

    By default, names ending in *_cleaned, *_spoofed, or *_dms are skipped so outputs next to sources do not loop.
    Use --collect-subfolder to write under dms_cleaned/, and --all with it to process those suffixes too.
    Files created under dms_cleaned/ are always ignored.
    """

    if include_all and not collect_subfolder:
        raise typer.BadParameter(
            "--all requires --collect-subfolder so outputs go under dms_cleaned/ and names like *_cleaned do not re-trigger the watcher.",
            param_hint="--all",
        )

    try:
        mode = _validate_mode(mode)
        print_banner()
        folder.mkdir(parents=True, exist_ok=True)
        output_dir: Path | None = (folder / "dms_cleaned") if collect_subfolder else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        if include_all and output_dir is not None:
            console.print(
                "[bold bright_blue]Watch:[/bold bright_blue] "
                "[yellow]--all[/yellow] is on — processing every new file, including names like "
                "[yellow]*_cleaned[/yellow], [yellow]*_spoofed[/yellow], [yellow]*_dms[/yellow]. "
                "[dim]Anything created under dms_cleaned/ is still ignored.[/dim]"
            )
        else:
            console.print(
                "[bold bright_blue]Watch:[/bold bright_blue] "
                "skipping new files whose names end with "
                "[yellow]*_cleaned[/yellow], [yellow]*_spoofed[/yellow], or [yellow]*_dms[/yellow] "
                "[dim](avoids feedback loops). Use [bold]--all[/bold] with [bold]--collect-subfolder[/bold] to include them.[/dim]"
            )

        rows: deque[dict[str, object]] = deque(maxlen=20)
        processed = {"ok": 0, "failed": 0}

        def render_live() -> Group:
            dest_note = f"  |  Out: {output_dir}" if output_dir else ""
            all_note = "  |  --all" if include_all else ""
            table = Table(
                title=f"Watching: {folder}  |  Mode: {mode}{dest_note}{all_note}  |  Ctrl+C to stop",
                box=box.ROUNDED,
                header_style="bold bright_white",
            )
            table.add_column("Time", style="dim white", width=10)
            table.add_column("File", style="bright_white", width=40)
            table.add_column("Fields", style="bright_cyan", width=8)
            table.add_column("Status", width=12)
            for entry in list(rows):
                color = "green" if entry["ok"] else "red"
                table.add_row(
                    str(entry["time"]),
                    str(entry["file"]),
                    str(entry["fields"]),
                    f"[{color}]{entry['status']}[/{color}]",
                )
            footer = Text(f"Processed {processed['ok'] + processed['failed']} files", style="dim white")
            return Group(table, footer)

        def on_file(path: Path, fields_count: int, success: bool) -> None:
            rows.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "file": path.name,
                    "fields": fields_count,
                    "status": "✓ done" if success else "✗ error",
                    "ok": success,
                }
            )
            if success:
                processed["ok"] += 1
            else:
                processed["failed"] += 1

        observer = Observer()
        observer.schedule(
            DMSEventHandler(
                mode=mode,
                callback=on_file,
                output_dir=output_dir,
                include_all=include_all,
                strip_annotations=strip_annotations,
                strip_attachments=strip_attachments,
            ),
            str(folder),
            recursive=recursive,
        )
        observer.start()
        try:
            with Live(render_live(), console=console, refresh_per_second=4) as live:
                while True:
                    live.update(render_live())
                    time.sleep(0.1)
        except KeyboardInterrupt:
            observer.stop()
            console.print(f"\n[dim white]Stopped. Processed {processed['ok'] + processed['failed']} files.[/dim white]")
        finally:
            observer.join()
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def batch(
    files: list[Path] = typer.Argument(..., help="Files and/or globs to process."),
    mode: str = typer.Option("clean", "--mode", help="clean, spoof, or spoof_clean (spoof + strip residual fields)."),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Optional folder for outputs (*_cleaned / *_spoofed); created if missing.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
    residual: bool = typer.Option(
        False,
        "--residual",
        help="After spoof, offer to strip leftover sensitive fields.",
    ),
    strip_annotations: bool = typer.Option(
        False,
        "--strip-annotations",
        help="Also remove PDF annotations and comments (text, popups).",
    ),
    strip_attachments: bool = typer.Option(
        False,
        "--strip-attachments",
        help="Also remove PDF embedded file attachments.",
    ),
) -> None:
    """Clean or spoof many files in one run (no live watching)."""

    try:
        mode = _validate_mode(mode)
        print_banner()
        expanded = _expand_batch_inputs(files)
        if not expanded:
            print_error("No matching files found.")
            raise typer.Exit(1)
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
        if not _confirm(f"Process {len(expanded)} files in {mode} mode?", yes=yes):
            raise typer.Exit()

        targets = {file: _batch_target(file, output_dir, mode) for file in expanded}
        existing_targets = sum(1 for target in targets.values() if target.exists())
        if existing_targets and not _confirm(
            f"{existing_targets} output file(s) already exist. Overwrite?",
            yes=yes,
        ):
            raise typer.Exit(1)

        summary: list[tuple[str, str, str, str]] = []
        succeeded = failed = skipped = 0

        progress_columns = [
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        ]
        with Progress(*progress_columns, console=console) as progress:
            overall = progress.add_task("Overall", total=len(expanded))
            tasks = {file: progress.add_task(file.name, total=100) for file in expanded}

            for file in expanded:
                try:
                    report = analyzer.analyze(file)
                    sensitive = _risk_count(report)
                    if sensitive == 0 and report.analysis_status == "ok":
                        skipped += 1
                        summary.append((file.name, "0", "skipped", "—"))
                        progress.update(tasks[file], completed=100, description=f"{file.name} skipped")
                        progress.advance(overall)
                        continue
                    if report.analysis_status != "ok":
                        console.print(f"[bold yellow]! {file.name}:[/bold yellow] {report.analysis_error or 'metadata could not be read completely.'}")

                    if mode in {"spoof", "spoof_clean"}:
                        if report.analysis_status != "ok":
                            failed += 1
                            summary.append((file.name, "—", "unverified", "✗"))
                            progress.update(tasks[file], completed=100, description=f"{file.name} unverified")
                            progress.advance(overall)
                            continue
                        progress.update(tasks[file], description=f"{file.name} spoofing")
                        output = targets[file]
                        use_residual = residual or (mode == "spoof_clean")
                        result, _, info_codes, fields_changed, removed_residual, _, _ = _process_spoof(
                            file,
                            output,
                            residual=use_residual,
                            auto_remove_residual=use_residual,
                        )
                        succeeded += 1
                        if removed_residual:
                            action = "spoofed+cleaned"
                        elif info_codes:
                            action = "spoofed(partial)"
                        else:
                            action = "spoofed"
                        summary.append((result.name, str(fields_changed), action, "✓"))
                    else:
                        progress.update(tasks[file], description=f"{file.name} cleaning")
                        output = targets[file]
                        result, removed = _process_clean(
                            file,
                            output,
                            strip_annotations=strip_annotations,
                            strip_attachments=strip_attachments,
                        )
                        try:
                            leftover = analyzer.verify(result)
                        except analyzer.MetadataAnalysisError as exc:
                            failed += 1
                            summary.append((result.name, str(removed), f"unverified: {exc}", "✗"))
                        else:
                            if leftover:
                                failed += 1
                                summary.append((result.name, str(removed), f"cleaned, {len(leftover)} left", "✗"))
                            else:
                                succeeded += 1
                                summary.append((result.name, str(removed), "cleaned", "✓"))

                    progress.update(tasks[file], completed=100)
                    progress.advance(overall)
                except Exception as exc:
                    logging.error("batch failed for %s: %s", file, exc, exc_info=True)
                    failed += 1
                    summary.append((file.name, "—", "failed", "✗"))
                    progress.update(tasks[file], completed=100, description=f"{file.name} failed")
                    progress.advance(overall)

        table = Table(box=box.ROUNDED, header_style="bold bright_white")
        table.add_column("File", style="bright_cyan")
        table.add_column("Fields", justify="right")
        table.add_column("Action")
        table.add_column("Status", justify="center")
        for file_name, fields, action, status in summary:
            table.add_row(file_name, fields, action, status)
        console.print(table)
        console.print(f"[bold green]{succeeded} succeeded[/bold green], [bold red]{failed} failed[/bold red], [bold yellow]{skipped} skipped[/bold yellow].")
        if output_dir:
            console.print(f"[dim white]Saved to:[/dim white] {output_dir}")
        if failed:
            raise typer.Exit(1)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


if __name__ == "__main__":
    app()
