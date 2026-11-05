"""Diagnostics."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from engg_math_cli import _doctor as doc
from engg_math_cli import _workspace as ws
from engg_math_cli._app import State, app
from engg_math_cli._runner import RunResult, SubprocessRunner, require_success
from tests.conftest import FakeRunner

if TYPE_CHECKING:
    from pathlib import Path


def probe(dists: dict[str, tuple[str, list[str]]], **extra: Any) -> dict[str, Any]:
    return {
        "python": "3.13.0",
        "dists": {n: {"version": v, "requires": r} for n, (v, r) in dists.items()},
        **extra,
    }


def test_compatibility_ok_and_failures() -> None:
    """REQ-CLI-030: ecosystem requirements must be met by installed versions."""
    good = probe(
        {
            "engg-math-core": ("0.1.0", []),
            "engg-math-linear-systems": ("0.1.0", ["engg-math-core>=0.1,<0.2", "numpy>=1.26"]),
        }
    )
    assert doc.check_compatibility(good).status == "ok"
    old = probe(
        {
            "engg-math-core": ("0.3.0", []),
            "engg-math-linear-systems": ("0.1.0", ["engg-math-core>=0.1,<0.2"]),
        }
    )
    assert "found 0.3.0" in doc.check_compatibility(old).detail
    missing = probe({"engg-math-linear-systems": ("0.1.0", ["engg-math-core>=0.1"])})
    result = doc.check_compatibility(missing)
    assert result.status == "fail"
    assert "not installed" in result.detail


def test_compatibility_ignores_extras_and_unparseable() -> None:
    p = probe(
        {
            "engg-math-linear-systems": (
                "0.1.0",
                ["engg-math-viz>=0.1 ; extra == 'viz'", "not a requirement!!", "numpy"],
            )
        }
    )
    assert doc.check_compatibility(p).status == "ok"
    assert doc.check_compatibility(None).status == "skip"


def test_environment_and_backend() -> None:
    assert doc.check_environment(None).status == "warn"
    empty = probe({})
    assert "no ecosystem" in doc.check_environment(empty).detail
    listed = doc.check_environment(probe({"engg-math-core": ("0.1.0", [])}))
    assert "core 0.1.0" in listed.detail
    assert doc.check_backend(None).status == "skip"
    assert doc.check_backend(probe({})).status == "skip"
    ok = doc.check_backend(probe({}, numpy="2.1", blas="openblas", lapack="openblas"))
    assert ok.status == "ok"
    assert "openblas" in ok.detail
    assert doc.check_backend(probe({}, numpy="2.1", blas=None)).status == "warn"


def test_python_check(monkeypatch: pytest.MonkeyPatch) -> None:
    assert doc.check_python(None).status == "ok"
    assert doc.check_python(ws.Manifest("lab", python=">=99")).status == "warn"
    monkeypatch.setattr(sys, "version_info", (3, 10, 0, "final", 0))
    assert doc.check_python(None).status == "fail"


def test_uv_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _n: None)
    assert doc.check_uv(FakeRunner()).status == "fail"
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/uv")
    ok = doc.check_uv(FakeRunner(respond=lambda _a: RunResult(0, "uv 0.12.0\n", "")))
    assert ok.detail == "uv 0.12.0"


def test_manifest_and_consistency_checks(tmp_path: Path) -> None:
    check, manifest = doc.check_manifest(None)
    assert check.status == "fail"
    assert manifest is None
    (tmp_path / ws.MANIFEST).write_text("bogus = 1", encoding="utf-8")
    assert doc.check_manifest(tmp_path)[0].status == "fail"
    good = ws.Manifest("lab", modules={"core": "*"})
    ws.save(tmp_path, good)
    (tmp_path / ws.PYPROJECT).write_text(ws.new_pyproject(good), encoding="utf-8")
    assert doc.check_manifest(tmp_path)[0].status == "ok"
    drift = doc.check_consistency(tmp_path, good)
    assert drift.status == "warn"
    assert "engg-math-core" in drift.detail
    ws.sync_pyproject(tmp_path, good)
    assert doc.check_consistency(tmp_path, good).status == "ok"


def test_probe_environment(tmp_path: Path) -> None:
    runner = FakeRunner(respond=lambda _a: RunResult(0, json.dumps(probe({})), ""))
    assert doc.probe_environment(tmp_path, runner) is None
    python = doc.venv_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_text("")
    assert doc.probe_environment(tmp_path, runner) == probe({})
    broken = FakeRunner(respond=lambda _a: RunResult(1, "", "boom"))
    assert doc.probe_environment(tmp_path, broken) is None


def test_probe_script_runs_in_a_real_interpreter() -> None:
    """REQ-CLI-031: the embedded probe executes and emits the expected keys."""
    result = SubprocessRunner().run([sys.executable, "-c", doc.PROBE])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert {"python", "dists", "blas", "lapack"} <= set(data)


def test_vulnerability_check_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    assert doc.check_vulnerabilities(None, runner, enabled=False).detail.startswith("run with")
    assert "no uv.lock" in doc.check_vulnerabilities(tmp_path, runner, enabled=True).detail
    (tmp_path / "uv.lock").write_text("")
    monkeypatch.setattr("shutil.which", lambda _n: None)
    assert "not installed" in doc.check_vulnerabilities(tmp_path, runner, enabled=True).detail
    monkeypatch.setattr("shutil.which", lambda _n: "/bin/pip-audit")
    assert doc.check_vulnerabilities(tmp_path, runner, enabled=True).status == "ok"
    bad_export = FakeRunner(respond=lambda a: RunResult(1 if a[0] == "uv" else 0, "", ""))
    assert doc.check_vulnerabilities(tmp_path, bad_export, enabled=True).status == "warn"
    vulnerable = FakeRunner(
        respond=lambda a: RunResult(0, "", "") if a[0] == "uv" else RunResult(1, "CVE-1 in x", "")
    )
    found = doc.check_vulnerabilities(tmp_path, vulnerable, enabled=True)
    assert found.status == "fail"
    assert "CVE-1" in found.detail


def test_run_doctor_outside_a_workspace(tmp_path: Path) -> None:
    checks = doc.run_doctor(tmp_path, FakeRunner())
    by_name = {c.name: c for c in checks}
    assert by_name["manifest"].status == "fail"
    assert by_name["environment"].status == "skip"


def test_run_doctor_in_a_workspace_with_environment(tmp_path: Path) -> None:
    manifest = ws.Manifest("lab", modules={"core": "*"})
    ws.save(tmp_path, manifest)
    (tmp_path / ws.PYPROJECT).write_text(ws.new_pyproject(manifest), encoding="utf-8")
    ws.sync_pyproject(tmp_path, manifest)
    python = doc.venv_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_text("")
    payload = probe(
        {"engg-math-core": ("0.1.0", [])}, numpy="2.1", blas="accelerate", lapack="accelerate"
    )
    runner = FakeRunner(respond=lambda _a: RunResult(0, json.dumps(payload), ""))
    checks = {c.name: c for c in doc.run_doctor(tmp_path, runner)}
    assert checks["manifest"].status == "ok"
    assert checks["environment"].status == "ok"
    assert checks["blas/lapack"].status == "ok"
    assert doc.as_dicts(list(checks.values()))[0]["name"] == "python"


def test_doctor_command_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    """REQ-CLI-032: unhealthy means exit 1; --json carries the same verdict."""
    cli = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = cli.invoke(app, ["--json", "doctor"], obj=State(json_mode=True, runner=runner))
    assert result.exit_code == 1
    assert json.loads(result.stdout)["data"]["healthy"] is False
    human = cli.invoke(app, ["doctor"], obj=State(json_mode=False, runner=runner))
    assert human.exit_code == 1
    assert "manifest" in human.stdout


def test_doctor_command_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    cli = CliRunner()
    monkeypatch.chdir(tmp_path)
    cli.invoke(app, ["init", "lab"], obj=State(json_mode=False, runner=runner))
    monkeypatch.chdir(tmp_path / "lab")
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/uv")
    result = cli.invoke(app, ["--json", "doctor"], obj=State(json_mode=True, runner=runner))
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["healthy"] is True


def test_runner_error_paths() -> None:
    from engg_math_cli._errors import ToolchainError  # noqa: PLC0415

    with pytest.raises(ToolchainError, match="not found"):
        SubprocessRunner().run(["definitely-not-a-real-binary-xyz"])
    with pytest.raises(ToolchainError, match="boom"):
        require_success(RunResult(3, "", "a\nboom"), "`x`")
