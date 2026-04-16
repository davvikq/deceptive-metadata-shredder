"""CLI validation for dms watch."""

from pathlib import Path

from typer.testing import CliRunner

from dms.interfaces import cli

runner = CliRunner()


def test_watch_all_requires_collect_subfolder(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["watch", str(tmp_path), "--all"])
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "collect-subfolder" in combined.lower()
