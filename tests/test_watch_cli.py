"""CLI validation for dms watch."""

import re
from pathlib import Path

from typer.testing import CliRunner

from dms.interfaces import cli

runner = CliRunner()


def test_watch_all_requires_collect_subfolder(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["watch", str(tmp_path), "--all"])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    # Rich/Typer can render ANSI output in CI; normalize before substring assertions.
    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", combined).lower()
    assert (
        "collect-subfolder" in cleaned
        or "--all" in cleaned
        or "requires" in cleaned
    )
