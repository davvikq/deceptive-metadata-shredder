"""Rich-powered command line interface."""

from __future__ import annotations

import json
import logging
import shutil
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
from dms.core.models import FileReport, MetaField, SpoofProfile
from dms.core.sanitizer import remove_all
from dms.core.spoofer import apply_smart_spoof, apply_spoof
from dms.core.utils import get_subprocess_flags
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

CLI_LINKED_TAGS = {
    "datetimeoriginal": ["date/time original", "datetime original", "subsectimeoriginal"],
    "createdate": ["date created", "creation date", "captured at"],
    "modifydate": ["modified at", "pdf modified", "metadata date"],
    "gpsdatetime": ["gps date stamp", "gps time stamp", "gps date/time"],
    "gpslatitude": ["gps position", "gps latitude ref", "gps longitude ref", "gps longitude", "gps altitude", "gps altitude ref"],
    "make": ["device make", "device model", "lens model", "lens id", "lens make", "creator tool", "software", "model"],
    "author": ["creator", "artist", "xmp:creator", "dc:creator"],
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
            text=True,
            check=False,
            creationflags=get_subprocess_flags(),
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


def _expand_linked_keys(keys: set[str]) -> set[str]:
    expanded = {_canonical_key(key) for key in keys if key}
    for key in list(expanded):
        for source, linked in CLI_LINKED_TAGS.items():
            linked_set = {_canonical_key(item) for item in linked}
            if source in key or key in source or key in linked_set:
                expanded.add(source)
                expanded.update(linked_set)
    return expanded


def _cli_spoofed_keys(report: FileReport, changes: list[str]) -> set[str]:
    keys: set[str] = set()
    for field in report.fields:
        if "gps" in changes and field.category == "gps":
            keys.add(field.key)
        elif "device" in changes and field.category == "device":
            keys.add(field.key)
        elif "dates" in changes and field.category == "dates":
            keys.add(field.key)
        elif "author" in changes and field.category == "author":
            keys.add(field.key)
        elif "software" in changes and "software" in field.key.lower():
            keys.add(field.key)
    return _expand_linked_keys(keys)


def _apply_cli_statuses(report: FileReport, spoofed_keys: set[str] | None = None, removed_keys: set[str] | None = None) -> None:
    spoofed = {_canonical_key(key) for key in (spoofed_keys or set())}
    removed = {_canonical_key(key) for key in (removed_keys or set())}
    for field in report.fields:
        aliases = _field_aliases(field)
        if aliases & removed:
            field.status = "removed"
        elif aliases & spoofed:
            field.status = "spoofed"
        else:
            field.status = "risk" if field.is_sensitive else "clean"


def _risk_count(report: FileReport) -> int:
    return sum(1 for field in report.fields if field.status == "risk")


def _serialize_report(report: FileReport) -> dict[str, Any]:
    return {
        "path": str(report.path),
        "file_type": report.file_type,
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
    console.print("[dim white]Supported formats:[/dim white] JPG PNG HEIC TIFF WebP RAW PDF DOCX MP4")
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
    categories = len([1 for _, fields in _group_fields(report) if any(field.status == "risk" for field in fields)])
    console.print(f"[bold bright_white]Summary:[/bold bright_white] {sensitive} sensitive fields found across {categories} categories.")


def _render_minimal(report: FileReport) -> None:
    for field in report.fields:
        console.print(f"{field.exiftool_tag}={_field_value(field.value)}")


def _command_summary() -> Table:
    table = Table(box=box.ROUNDED, header_style="bold bright_white")
    table.add_column("Command", style="bright_cyan")
    table.add_column("What it does", style="white")
    table.add_row("dms analyze <file>", "Show all fields and highlight sensitive metadata")
    table.add_row("dms clean <file>", "Write a copy with metadata stripped (*_cleaned by default)")
    table.add_row("dms spoof <file>", "Replace GPS/device/dates/author with plausible values")
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
        lat_text, lon_text = [part.strip() for part in value.split(",", 1)]
        return "manual", (float(lat_text), float(lon_text))
    raise typer.BadParameter("Use smart, remove, or lat,lon.")


def _parse_dates_argument(value: str) -> tuple[str, int]:
    lowered = value.lower().strip()
    if lowered in {"random", "remove", "keep"}:
        return lowered, 0
    if lowered.startswith("shift:"):
        return "shift", int(lowered.split(":", 1)[1])
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
    raise typer.BadParameter(f"Unknown device id: {option}")


def _default_spoof_output(path: Path, output: Path | None) -> Path:
    return output or path.with_name(f"{path.stem}_spoofed{path.suffix}")


def _move_result(result_path: Path, target: Path) -> Path:
    if result_path.resolve() == target.resolve():
        return result_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.move(str(result_path), str(target))
    return target


def _preview_spoof_plan(report: FileReport, profile: SpoofProfile, smart: bool) -> tuple[Table, list[str]]:
    table = Table(box=box.ROUNDED, header_style="bold bright_white")
    table.add_column("Field", style="bright_cyan")
    table.add_column("Original", style="white", overflow="fold")
    table.add_column("Will become", style="bold bright_magenta", overflow="fold")
    changes: list[str] = []

    gps_lat = report.by_key().get("GPSLatitude")
    gps_lon = report.by_key().get("GPSLongitude")
    if gps_lat and gps_lon and gps_lat.value not in (None, "") and gps_lon.value not in (None, ""):
        target = "~same country (random)" if smart or profile.gps_mode == "smart" else "removed" if profile.gps_mode == "remove" else str(profile.gps_target)
        table.add_row("GPS Location", f"{gps_lat.value}, {gps_lon.value}", target)
        changes.append("gps")

    make = report.by_key().get("Make")
    model = report.by_key().get("Model")
    if make or model:
        device_text = "random device"
        if profile.device_make and profile.device_model:
            device_text = f"{profile.device_make} {profile.device_model}"
        elif smart:
            current_make = str(make.value) if make and make.value else None
            current_model = str(model.value) if model and model.value else None
            candidates = [item for item in get_all_devices() if item.make != current_make or item.model != current_model]
            if candidates:
                device_text = f"{candidates[0].make} {candidates[0].model}"
        table.add_row("Device Model", f"{make.value if make else '—'} {model.value if model else ''}".strip(), device_text)
        changes.append("device")

    date_field = next((field for field in report.fields if field.category == "dates"), None)
    if date_field:
        if smart or profile.dates_mode == "random":
            target = "random past date"
        elif profile.dates_mode == "remove":
            target = "removed"
        elif profile.dates_mode == "shift":
            target = f"shifted by {profile.dates_shift_days} days"
        else:
            target = str(date_field.value)
        table.add_row("Create Date", _field_value(date_field.value), target)
        changes.append("dates")

    author_field = next((field for field in report.fields if field.category == "author"), None)
    if author_field and (smart or profile.author is not None):
        target = "random name" if smart or profile.author == "random" else "removed" if profile.author == "" else str(profile.author)
        table.add_row("Author", _field_value(author_field.value), target)
        changes.append("author")

    return table, changes


def _estimate_changed_fields(report: FileReport, changes: list[str]) -> int:
    total = 0
    for field in report.fields:
        if "gps" in changes and field.category == "gps":
            total += 1
        elif "device" in changes and field.category == "device":
            total += 1
        elif "dates" in changes and field.category == "dates":
            total += 1
        elif "author" in changes and field.category == "author":
            total += 1
        elif "software" in changes and "software" in field.key.lower():
            total += 1
    return total


def _expand_batch_inputs(files: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for file in files:
        pattern = str(file)
        if any(token in pattern for token in ["*", "?", "["]):
            expanded.extend(sorted(Path().glob(pattern)))
        else:
            expanded.append(file)
    return [path for path in expanded if path.exists() and path.is_file()]


def _remove_residual_fields(path: Path, fields: list[MetaField]) -> int:
    removable = [field for field in fields if not field.is_computed]
    if not removable:
        return 0
    exiftool = require_exiftool()
    args = [exiftool]
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
    result = subprocess.run(args, capture_output=True, text=True, check=False, creationflags=get_subprocess_flags())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to remove residual fields.")
    return applied


def _residual_fields(report: FileReport, spoofed_keys: set[str]) -> list[MetaField]:
    keys = {_canonical_key(key) for key in spoofed_keys}
    residual: list[MetaField] = []
    for field in report.fields:
        if not field.is_sensitive or field.is_computed:
            continue
        if _field_aliases(field) & keys:
            continue
        residual.append(field)
    return residual


def _print_info_codes(info_codes: list[str]) -> None:
    for code in info_codes:
        message = CLI_INFO_MESSAGES.get(code, code)
        console.print(f"[yellow]• {message}[/yellow]")


def _process_clean(file: Path, output: Path | None = None) -> tuple[Path, int]:
    report = analyzer.analyze(file)
    sensitive = _risk_count(report)
    result = remove_all(file, output)
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
    result, changes, info_codes = apply_smart_spoof(report)
    final_path = _move_result(result, _default_spoof_output(file, output))
    changed_fields = _estimate_changed_fields(report, changes)
    spoofed_keys = _cli_spoofed_keys(report, changes)
    reloaded = analyzer.analyze(final_path)
    _apply_cli_statuses(reloaded, spoofed_keys=spoofed_keys)
    removed_residual = 0
    if residual and auto_remove_residual:
        removed_residual = _remove_residual_fields(final_path, _residual_fields(reloaded, spoofed_keys))
        reloaded = analyzer.analyze(final_path)
        _apply_cli_statuses(reloaded, spoofed_keys=spoofed_keys)
    return final_path, changes, info_codes, changed_fields, removed_residual, original_risk, _risk_count(reloaded)


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
            console.print(json.dumps(_serialize_report(report), default=str, ensure_ascii=False))
            return
        if lowered == "minimal":
            _render_minimal(report)
            return
        print_banner()
        _render_analysis_table(report)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


@app.command()
def clean(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source file."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Destination path; default is sibling *_cleaned."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt."),
) -> None:
    """Remove all metadata into a new file (original is left unchanged)."""

    try:
        _ensure_supported(file)
        print_banner()
        report = analyzer.analyze(file)
        sensitive = _risk_count(report)
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
            result = remove_all(file, output)
            progress.update(task, completed=100)

        console.print(f"[bold green]✓ Cleaned:[/bold green] {result.name}")
        console.print(f"Removed [bold red]{sensitive}[/bold red] sensitive fields.")
        console.print(f"[dim white]Saved to:[/dim white] {result}")
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
    device: str | None = typer.Option(None, "--device", help="Device id from bundled DB, or omit for smart."),
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
            if not yes and not typer.confirm("Proceed?", default=False):
                raise typer.Abort()
        original_risk = _risk_count(report)
        gps_mode, gps_target = _parse_gps_argument(gps)
        dates_mode, dates_shift_days = _parse_dates_argument(dates)
        profile = SpoofProfile(gps_mode=gps_mode, gps_target=gps_target, dates_mode=dates_mode, dates_shift_days=dates_shift_days)

        smart = device is None and author is None and gps == "smart" and dates == "random"
        if device:
            make, model = _resolve_device_option(device)
            profile.device_make = make
            profile.device_model = model
        if author:
            profile.author = "" if author == "remove" else author

        plan_table, planned_changes = _preview_spoof_plan(report, profile, smart)
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
                result, changes, info_codes = apply_smart_spoof(report)
                changed_fields = _estimate_changed_fields(report, changes)
                progress.update(task, advance=4)
                final_path = _move_result(result, _default_spoof_output(file, output))
            else:
                progress.update(task, description="[1/4] Preparing spoof plan...")
                progress.advance(task)
                progress.update(task, description="[2/4] Writing spoofed metadata...")
                result = apply_spoof(report, profile)
                progress.advance(task)
                progress.update(task, description="[3/4] Finalizing output...")
                final_path = _move_result(result, _default_spoof_output(file, output))
                progress.advance(task)
                progress.update(task, description="[4/4] Done")
                progress.advance(task)
                changes = planned_changes
                changed_fields = _estimate_changed_fields(report, changes)

        spoofed_keys = _cli_spoofed_keys(report, changes)
        reloaded = analyzer.analyze(final_path)
        _apply_cli_statuses(reloaded, spoofed_keys=spoofed_keys)

        removed_residual = 0
        if residual:
            residual_candidates = _residual_fields(reloaded, spoofed_keys)
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
                    removed_residual = _remove_residual_fields(final_path, residual_candidates)
                    reloaded = analyzer.analyze(final_path)
                    _apply_cli_statuses(reloaded, spoofed_keys=spoofed_keys, removed_keys={field.key for field in residual_candidates})

        final_risk = _risk_count(reloaded)
        console.print(f"[bold bright_magenta]✓ Spoofed:[/bold bright_magenta] {final_path.name}")
        console.print(f"Changed [bold bright_magenta]{len(changes)}[/bold bright_magenta] categories, [bold bright_magenta]{changed_fields}[/bold bright_magenta] fields.")
        if removed_residual:
            console.print(f"[bold green]✓ Removed[/bold green] {removed_residual} residual fields")
        if info_codes:
            _print_info_codes(info_codes)
        console.print(f"[dim white]Saved to:[/dim white] {final_path}")
        console.print(f"Risk reduced: [bold red]{original_risk}[/bold red] → [bold green]{final_risk}[/bold green] fields")
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
        help="clean: strip metadata. spoof: smart spoof (needs exiftool).",
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
    mode: str = typer.Option("clean", "--mode", help="clean or spoof."),
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
) -> None:
    """Clean or spoof many files in one run (no live watching)."""

    try:
        print_banner()
        expanded = _expand_batch_inputs(files)
        if not expanded:
            print_error("No matching files found.")
            raise typer.Exit(1)
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
        if not _confirm(f"Process {len(expanded)} files in {mode} mode?", yes=yes):
            raise typer.Exit()

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
                    if sensitive == 0:
                        skipped += 1
                        summary.append((file.name, "0", "skipped", "—"))
                        progress.update(tasks[file], completed=100, description=f"{file.name} skipped")
                        progress.advance(overall)
                        continue

                    if mode == "spoof":
                        progress.update(tasks[file], description=f"{file.name} spoofing")
                        output = output_dir / f"{file.stem}_spoofed{file.suffix}" if output_dir else None
                        result, _, info_codes, fields_changed, removed_residual, _, _ = _process_spoof(
                            file,
                            output,
                            residual=residual,
                            auto_remove_residual=residual,
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
                        output = output_dir / f"{file.stem}_cleaned{file.suffix}" if output_dir else None
                        result, removed = _process_clean(file, output)
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
    except (typer.Exit, typer.Abort):
        raise
    except Exception as exc:
        handle_exception(exc)


if __name__ == "__main__":
    app()
