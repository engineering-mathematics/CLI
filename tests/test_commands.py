"""Command behaviour through the Typer app with a scripted runner."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from engg_math_cli import _workspace as ws
from engg_math_cli._app import State, app
from engg_math_cli._runner import RunResult
from tests.conftest import FakeRunner

if TYPE_CHECKING:
    from pathlib import Path

cli = CliRunner()


def invoke(runner: FakeRunner, *args: str, json_mode: bool = True) -> tuple[int, Any]:
    argv = (["--json"] if json_mode else []) + list(args)
    result = cli.invoke(app, argv, obj=State(json_mode=json_mode, runner=runner))
    body = json.loads(result.stdout) if json_mode and result.stdout.strip() else result.stdout
    return result.exit_code, body


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner) -> Path:
    monkeypatch.chdir(tmp_path)
    code, _ = invoke(runner, "init", "lab")
    assert code == 0
    monkeypatch.chdir(tmp_path / "lab")
    return tmp_path / "lab"


def test_init_creates_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    """REQ-CLI-020: init writes manifest, pyproject and README."""
    monkeypatch.chdir(tmp_path)
    code, body = invoke(runner, "init", "lab", "--source", "pypi")
    assert code == 0
    assert body["ok"] is True
    assert body["data"]["project"] == "lab"
    for name in (ws.MANIFEST, ws.PYPROJECT, "README.md"):
        assert (tmp_path / "lab" / name).is_file()
    assert ws.load(tmp_path / "lab").source == "pypi"


def test_init_refuses_non_empty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lab").mkdir()
    (tmp_path / "lab" / "keep.txt").write_text("x")
    code, body = invoke(runner, "init", "lab")
    assert code == 2
    assert body["ok"] is False
    assert body["error"]["exit_code"] == 2


def test_init_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    code, out = invoke(runner, "init", "lab", json_mode=False)
    assert code == 0
    assert "created" in out


def test_add_edits_files_and_runs_uv_sync(workspace: Path, runner: FakeRunner) -> None:
    """REQ-CLI-021: add resolves the name, records it and syncs via uv."""
    code, body = invoke(runner, "add", "linear_systems")
    assert code == 0
    assert body["data"]["package"] == "linear-systems"
    assert "engg-math-core" in body["data"]["installed"]
    assert ws.load(workspace).modules == {"linear-systems": "*"}
    assert runner.calls == [["uv", "sync"]]


def test_add_with_version_and_no_sync(workspace: Path, runner: FakeRunner) -> None:
    code, _ = invoke(runner, "add", "core", "--version", ">=0.1,<0.2", "--no-sync")
    assert code == 0
    assert ws.load(workspace).modules == {"core": ">=0.1,<0.2"}
    assert runner.calls == []


def test_add_rejects_bad_version_and_unknown_package(workspace: Path, runner: FakeRunner) -> None:
    assert invoke(runner, "add", "core", "--version", "latest")[0] == 2
    code, body = invoke(runner, "add", "linear-system")
    assert code == 3
    assert "did you mean" in body["error"]["message"]
    assert ws.load(workspace).modules == {}


def test_uv_failure_maps_to_exit_code_4(workspace: Path) -> None:
    """REQ-CLI-022: a failed uv call is reported with its stderr tail."""
    failing = FakeRunner(respond=lambda _a: RunResult(2, "", "resolution failed"))
    code, body = invoke(failing, "add", "core")
    assert code == 4
    assert "resolution failed" in body["error"]["message"]


def test_remove_prunes_and_reports_absent_package(workspace: Path, runner: FakeRunner) -> None:
    invoke(runner, "add", "dynamical-systems", "--no-sync")
    assert invoke(runner, "remove", "dynamical-systems", "--no-sync")[0] == 0
    assert ws.load(workspace).modules == {}
    assert "engg-math" not in (workspace / ws.PYPROJECT).read_text()
    code, body = invoke(runner, "remove", "dynamical-systems")
    assert code == 2
    assert "not in" in body["error"]["message"]


def test_remove_runs_sync(workspace: Path, runner: FakeRunner) -> None:
    invoke(runner, "add", "core", "--no-sync")
    invoke(runner, "remove", "core")
    assert runner.calls == [["uv", "sync"]]


def test_update_repins_and_upgrades(workspace: Path, runner: FakeRunner) -> None:
    """REQ-CLI-023: update rewrites sources then upgrades the lock."""
    invoke(runner, "add", "units", "--no-sync")
    text = (
        (workspace / ws.PYPROJECT)
        .read_text()
        .replace("ed62979978977e80bb25ef73e905fd28bab46c8e", "0" * 40)
    )
    (workspace / ws.PYPROJECT).write_text(text)
    assert invoke(runner, "update")[0] == 0
    assert "0" * 40 not in (workspace / ws.PYPROJECT).read_text()
    assert runner.calls == [["uv", "sync", "--upgrade"]]
    assert invoke(runner, "update", "--no-sync")[0] == 0


def test_commands_need_a_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    for command in (["add", "core"], ["remove", "core"], ["update"], ["list"], ["graph"]):
        code, body = invoke(runner, *command)
        assert code == 2, command
        assert body["error"]["type"] == "ConfigError"


def test_list_workspace_and_available(workspace: Path, runner: FakeRunner) -> None:
    invoke(runner, "add", "core", "--no-sync")
    _, body = invoke(runner, "list")
    assert body["data"] == [{"name": "core", "dist": "engg-math-core", "version": "*"}]
    _, everything = invoke(runner, "list", "--available")
    assert len(everything["data"]) >= 10
    code, text = invoke(runner, "list", "--available", json_mode=False)
    assert code == 0
    assert "linear-systems" in text


def test_info(workspace: Path, runner: FakeRunner) -> None:
    _, body = invoke(runner, "info", "continuous-analysis")
    assert body["data"]["required_by"] == ["dynamical-systems"]
    code, text = invoke(runner, "info", "continuous-analysis", json_mode=False)
    assert code == 0
    assert "engg-math-continuous-analysis" in text


def test_graph(workspace: Path, runner: FakeRunner) -> None:
    invoke(runner, "add", "dynamical-systems", "--no-sync")
    _, body = invoke(runner, "graph")
    assert body["data"] == {
        "dynamical-systems": ["core", "continuous-analysis", "units", "linear-systems"]
    } or set(body["data"]["dynamical-systems"]) == {
        "core",
        "continuous-analysis",
        "units",
        "linear-systems",
    }
    code, text = invoke(runner, "graph", json_mode=False)
    assert code == 0
    assert "linear-systems" in text


def test_version_flag(runner: FakeRunner) -> None:
    result = cli.invoke(app, ["--version"], obj=State(json_mode=False, runner=runner))
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_no_args_shows_help(runner: FakeRunner) -> None:
    result = cli.invoke(app, [], obj=State(json_mode=False, runner=runner))
    assert "Usage" in result.stdout


def test_default_state_is_built_without_injection() -> None:
    result = cli.invoke(app, ["--json", "list", "--available"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True


def test_no_color_is_honoured(monkeypatch: pytest.MonkeyPatch, runner: FakeRunner) -> None:
    """REQ-CLI-024: NO_COLOR removes colour codes even on a forced terminal."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    result = cli.invoke(app, ["list", "--available"], obj=State(json_mode=False, runner=runner))
    assert not re.search(r"\x1b\[(3[0-7]|9[0-7]|38|48)[;m]", result.stdout)


def test_output_is_plain_when_not_a_terminal(
    monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    """REQ-CLI-025: piped output carries no escape codes."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = cli.invoke(app, ["list", "--available"], obj=State(json_mode=False, runner=runner))
    assert "\x1b[" not in result.stdout


def test_console_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-CLI-026: `main` runs the app and exits with its status."""
    import engg_math_cli  # noqa: PLC0415

    monkeypatch.setattr("sys.argv", ["engg-math", "--version"])
    with pytest.raises(SystemExit) as info:
        engg_math_cli.main()
    assert info.value.code == 0
