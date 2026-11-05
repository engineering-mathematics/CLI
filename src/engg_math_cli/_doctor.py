"""Environment and workspace health checks."""

from __future__ import annotations

import json
import platform
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import _workspace as ws
from ._errors import CliError
from ._registry import DIST_PREFIX

if TYPE_CHECKING:
    from ._runner import Runner

Status = Literal["ok", "warn", "fail", "skip"]
MIN_PYTHON: Final = (3, 11)

# Runs inside the workspace environment: ecosystem distributions with their requirements, and the
# BLAS/LAPACK libraries NumPy was built against.
PROBE: Final = """
import importlib.metadata as m, json, sys
dists = {}
for d in m.distributions():
    n = d.metadata["Name"] or ""
    if n.lower().startswith("engg-math-"):
        dists[n.lower()] = {"version": d.version, "requires": list(d.requires or [])}
out = {"python": sys.version.split()[0], "dists": dists, "blas": None, "lapack": None}
try:
    import numpy
    deps = numpy.show_config(mode="dicts")["Build Dependencies"]
    out["blas"] = deps.get("blas", {}).get("name")
    out["lapack"] = deps.get("lapack", {}).get("name")
    out["numpy"] = numpy.__version__
except Exception as exc:
    out["numpy_error"] = type(exc).__name__
print(json.dumps(out))
"""


@dataclass(frozen=True, slots=True)
class Check:
    """One diagnostic result."""

    name: str
    status: Status
    detail: str


def venv_python(root: Path) -> Path:
    """Interpreter of the workspace's ``.venv``."""
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    return root / ".venv" / scripts / exe


def check_python(manifest: ws.Manifest | None) -> Check:
    """Check the interpreter against the ecosystem floor and the workspace constraint."""
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] < MIN_PYTHON:
        return Check("python", "fail", f"{version}; the ecosystem needs >= 3.11")
    if manifest and Version(version) not in SpecifierSet(manifest.python):
        return Check("python", "warn", f"{version} does not satisfy workspace {manifest.python}")
    return Check("python", "ok", f"{version} ({platform.python_implementation()})")


def check_uv(runner: Runner) -> Check:
    """``uv`` is installed."""
    if shutil.which("uv") is None:
        return Check("uv", "fail", "not found on PATH; see https://docs.astral.sh/uv/")
    try:
        result = runner.run(["uv", "--version"])
    except CliError as exc:
        return Check("uv", "fail", str(exc))
    return Check("uv", "ok", result.stdout.strip() or "version unknown")


def check_manifest(root: Path | None) -> tuple[Check, ws.Manifest | None]:
    """Check that the manifest parses and validates."""
    if root is None:
        return Check("manifest", "fail", f"no {ws.MANIFEST} found; run `engg-math init`"), None
    try:
        manifest = ws.load(root)
    except CliError as exc:
        return Check("manifest", "fail", str(exc)), None
    return Check("manifest", "ok", f"{manifest.project} at {root}"), manifest


def check_consistency(root: Path, manifest: ws.Manifest) -> Check:
    """Manifest modules and ``pyproject.toml`` agree."""
    declared = ws.declared_ecosystem_deps(root)
    expected = {f"{DIST_PREFIX}{name}" for name in manifest.modules}
    if declared == expected:
        return Check("pyproject", "ok", f"{len(expected)} module(s) match the manifest")
    drift = sorted(declared ^ expected)
    return Check("pyproject", "warn", f"out of step with manifest: {', '.join(drift)}")


def probe_environment(root: Path, runner: Runner) -> dict[str, Any] | None:
    """Run `PROBE` in the workspace environment; ``None`` if there is none."""
    python = venv_python(root)
    if not python.is_file():
        return None
    result = runner.run([str(python), "-c", PROBE])
    if result.returncode != 0:
        return None
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def check_environment(probe: dict[str, Any] | None) -> Check:
    """Check that the workspace environment exists and list its ecosystem packages."""
    if probe is None:
        return Check("environment", "warn", "no .venv; run `engg-math add <package>` or `uv sync`")
    dists = probe["dists"]
    listing = ", ".join(
        f"{n.removeprefix(DIST_PREFIX)} {d['version']}" for n, d in sorted(dists.items())
    )
    return Check("environment", "ok", listing or "no ecosystem packages installed")


def check_compatibility(probe: dict[str, Any] | None) -> Check:
    """Every installed package's ecosystem requirements are met by what is installed."""
    if probe is None:
        return Check("compatibility", "skip", "no environment")
    installed = {canonicalize_name(n): Version(d["version"]) for n, d in probe["dists"].items()}
    problems: list[str] = []
    for name, info in sorted(probe["dists"].items()):
        for text in info["requires"]:
            try:
                req = Requirement(text)
            except InvalidRequirement:
                continue
            dep = canonicalize_name(req.name)
            if not dep.startswith(DIST_PREFIX) or (
                req.marker and not req.marker.evaluate({"extra": ""})
            ):
                continue
            if dep not in installed:
                problems.append(f"{name} needs {dep}, not installed")
            elif not req.specifier.contains(installed[dep], prereleases=True):
                problems.append(f"{name} needs {dep}{req.specifier}, found {installed[dep]}")
    if problems:
        return Check("compatibility", "fail", "; ".join(problems))
    return Check("compatibility", "ok", f"{len(installed)} package(s) consistent")


def check_backend(probe: dict[str, Any] | None) -> Check:
    """Report the BLAS/LAPACK NumPy was built against."""
    if probe is None or "numpy" not in probe:
        return Check("blas/lapack", "skip", "NumPy not installed in the workspace")
    blas, lapack = probe.get("blas"), probe.get("lapack")
    if not blas:
        return Check("blas/lapack", "warn", f"NumPy {probe['numpy']}: backend not reported")
    return Check("blas/lapack", "ok", f"NumPy {probe['numpy']}: {blas} / {lapack}")


def check_vulnerabilities(root: Path | None, runner: Runner, *, enabled: bool) -> Check:
    """Audit locked runtime dependencies with ``pip-audit`` (opt-in: it uses the network)."""
    if not enabled:
        return Check("vulnerabilities", "skip", "run with --audit to query advisories")
    if root is None or not (root / "uv.lock").is_file():
        return Check("vulnerabilities", "skip", "no uv.lock")
    if shutil.which("pip-audit") is None:
        return Check("vulnerabilities", "skip", "pip-audit not installed")
    with tempfile.TemporaryDirectory() as tmp:
        reqs = Path(tmp) / "requirements.txt"
        export = [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "-o",
            str(reqs),
        ]
        if runner.run(export, root).returncode != 0:
            return Check("vulnerabilities", "warn", "could not export the lock file")
        audit = runner.run(["pip-audit", "-r", str(reqs), "--no-deps", "--disable-pip"], root)
    if audit.returncode == 0:
        return Check("vulnerabilities", "ok", "no known vulnerabilities")
    return Check("vulnerabilities", "fail", audit.stdout.strip() or audit.stderr.strip())


def run_doctor(start: Path | None, runner: Runner, *, audit: bool = False) -> list[Check]:
    """Run every check; later checks degrade to ``skip`` when their inputs are missing."""
    try:
        root: Path | None = ws.find_root(start)
    except CliError:
        root = None
    manifest_check, manifest = check_manifest(root)
    checks = [check_python(manifest), check_uv(runner), manifest_check]
    probe = None
    if root is not None and manifest is not None:
        checks.append(check_consistency(root, manifest))
        probe = probe_environment(root, runner)
    checks += [check_environment(probe) if root else Check("environment", "skip", "no workspace")]
    checks += [check_compatibility(probe), check_backend(probe)]
    checks.append(check_vulnerabilities(root, runner, enabled=audit))
    return checks


def as_dicts(checks: list[Check]) -> list[dict[str, str]]:
    """JSON form of the checks."""
    return [asdict(c) for c in checks]
