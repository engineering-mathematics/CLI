"""Manifest validation and pyproject derivation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import tomlkit

from engg_math_cli import _workspace as ws
from engg_math_cli._errors import ConfigError, UnknownPackageError

if TYPE_CHECKING:
    from pathlib import Path


def make(root: Path, **overrides: Any) -> ws.Manifest:
    manifest = ws.validate({"project": "lab", **overrides})
    ws.save(root, manifest)
    (root / ws.PYPROJECT).write_text(ws.new_pyproject(manifest), encoding="utf-8")
    return manifest


def test_roundtrip_sorts_modules(tmp_path: Path) -> None:
    """REQ-CLI-010: save/load preserves content and orders modules."""
    manifest = ws.validate(
        {"project": "lab", "modules": {"units": "*", "core": ">=0.1"}, "source": "pypi"}
    )
    ws.save(tmp_path, manifest)
    assert ws.load(tmp_path) == manifest
    assert (tmp_path / ws.MANIFEST).read_text().index("core") < (
        tmp_path / ws.MANIFEST
    ).read_text().index("units")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "project"),
        ({"project": "9bad"}, "project"),
        ({"project": "lab", "extra": 1}, "unknown keys"),
        ({"project": "lab", "python": 3}, "python"),
        ({"project": "lab", "python": "newer"}, "specifier"),
        ({"project": "lab", "source": "svn"}, "source"),
        ({"project": "lab", "modules": ["core"]}, "table"),
        ({"project": "lab", "modules": {"core": 1}}, "string"),
        ({"project": "lab", "modules": {"core": "latest"}}, "specifier"),
    ],
)
def test_invalid_manifests_are_rejected(raw: dict[str, Any], message: str) -> None:
    """REQ-CLI-011: the schema is enforced with exit code 2."""
    with pytest.raises(ConfigError, match=message) as info:
        ws.validate(raw)
    assert info.value.exit_code == 2


def test_unknown_module_name_is_rejected() -> None:
    with pytest.raises(UnknownPackageError):
        ws.validate({"project": "lab", "modules": {"linear-system": "*"}})


def test_module_spellings_are_normalised() -> None:
    manifest = ws.validate({"project": "lab", "modules": {"engg_math.linear_systems": "*"}})
    assert list(manifest.modules) == ["linear-systems"]


def test_load_reports_missing_and_malformed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        ws.load(tmp_path)
    (tmp_path / ws.MANIFEST).write_text("project = [", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        ws.load(tmp_path)


def test_find_root_walks_upward(tmp_path: Path) -> None:
    """REQ-CLI-012: commands work from any subdirectory."""
    make(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert ws.find_root(nested) == tmp_path.resolve()


def test_find_root_fails_outside_a_workspace(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="engg-math init"):
        ws.find_root(tmp_path)


def sources(root: Path) -> dict[str, Any]:
    doc = tomlkit.parse((root / ws.PYPROJECT).read_text(encoding="utf-8")).unwrap()
    found: dict[str, Any] = doc.get("tool", {}).get("uv", {}).get("sources", {})
    return found


def test_git_source_repeats_transitive_sources(tmp_path: Path) -> None:
    """REQ-CLI-013: uv sources do not propagate, so the whole closure is declared."""
    manifest = make(tmp_path, modules={"dynamical-systems": "*"})
    ws.sync_pyproject(tmp_path, manifest)
    assert set(sources(tmp_path)) == {
        "engg-math-core",
        "engg-math-units",
        "engg-math-linear-systems",
        "engg-math-continuous-analysis",
        "engg-math-dynamical-systems",
    }
    assert sources(tmp_path)["engg-math-core"]["subdirectory"] == "packages/core"


def test_pypi_source_declares_no_git_sources(tmp_path: Path) -> None:
    manifest = make(tmp_path, source="pypi", modules={"core": ">=0.1,<0.2"})
    ws.sync_pyproject(tmp_path, manifest)
    assert not sources(tmp_path)
    assert "engg-math-core>=0.1,<0.2" in (tmp_path / ws.PYPROJECT).read_text()


def test_sync_preserves_foreign_dependencies_and_prunes_sources(tmp_path: Path) -> None:
    """REQ-CLI-014: only ecosystem entries are managed."""
    manifest = make(tmp_path, modules={"linear-systems": "*"})
    path = tmp_path / ws.PYPROJECT
    doc: Any = tomlkit.parse(path.read_text(encoding="utf-8"))
    doc["project"]["dependencies"].append("requests>=2")
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    ws.sync_pyproject(tmp_path, manifest)
    emptied = ws.Manifest("lab", manifest.python, manifest.source, {})
    ws.sync_pyproject(tmp_path, emptied)
    text = path.read_text()
    assert "requests>=2" in text
    assert "engg-math" not in text


def test_sync_requires_pyproject(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        ws.sync_pyproject(tmp_path, ws.Manifest("lab"))


def test_declared_ecosystem_deps(tmp_path: Path) -> None:
    assert ws.declared_ecosystem_deps(tmp_path) == set()
    manifest = make(tmp_path, modules={"core": "*"})
    ws.sync_pyproject(tmp_path, manifest)
    assert ws.declared_ecosystem_deps(tmp_path) == {"engg-math-core"}
