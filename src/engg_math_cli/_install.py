"""Workspace mutations: init, add, remove, update."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from . import _workspace as ws
from ._errors import ConfigError
from ._registry import closure, resolve
from ._runner import require_success

if TYPE_CHECKING:
    from pathlib import Path

    from ._runner import Runner

README_TEMPLATE = (
    "# {project}\n\nEngineering Mathematics workspace. Manage packages with `engg-math`.\n"
)


def init_workspace(parent: Path, name: str, python: str, source: str) -> Path:
    """Create ``parent/name`` with a manifest, ``pyproject.toml`` and README."""
    root = parent / name
    if root.exists() and any(root.iterdir()):
        raise ConfigError(f"{root} already exists and is not empty")
    manifest = ws.validate({"project": name, "python": python, "source": source})
    root.mkdir(parents=True, exist_ok=True)
    ws.save(root, manifest)
    (root / ws.PYPROJECT).write_text(ws.new_pyproject(manifest), encoding="utf-8")
    (root / "README.md").write_text(README_TEMPLATE.format(project=name), encoding="utf-8")
    return root


def _apply(root: Path, manifest: ws.Manifest, runner: Runner | None) -> None:
    ws.save(root, manifest)
    ws.sync_pyproject(root, manifest)
    if runner is not None:
        require_success(runner.run(["uv", "sync"], root), "`uv sync`")


def add_module(root: Path, name: str, constraint: str, runner: Runner | None) -> list[str]:
    """Add ``name`` (and, from git, its dependency closure) and sync; return the dists added."""
    pkg = resolve(name)
    manifest = ws.load(root)
    if constraint != ws.ANY_VERSION:
        ws.validate({"project": manifest.project, "modules": {pkg.name: constraint}})
    modules = {**manifest.modules, pkg.name: constraint}
    _apply(root, replace(manifest, modules=modules), runner)
    return [p.dist for p in closure(pkg.name)]


def remove_module(root: Path, name: str, runner: Runner | None) -> None:
    """Remove ``name`` from the manifest and sync; unused git sources are pruned."""
    pkg = resolve(name)
    manifest = ws.load(root)
    if pkg.name not in manifest.modules:
        raise ConfigError(f"{pkg.name} is not in {ws.MANIFEST}")
    modules = {k: v for k, v in manifest.modules.items() if k != pkg.name}
    _apply(root, replace(manifest, modules=modules), runner)


def update_workspace(root: Path, runner: Runner | None) -> None:
    """Re-pin git sources to the revisions this CLI knows, then upgrade the lock."""
    manifest = ws.load(root)
    ws.sync_pyproject(root, manifest)
    if runner is not None:
        require_success(runner.run(["uv", "sync", "--upgrade"], root), "`uv sync --upgrade`")
