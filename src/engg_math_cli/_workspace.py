"""The ``engg-math.toml`` manifest and the workspace ``pyproject.toml`` it drives."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from ._errors import ConfigError
from ._registry import DEFAULT_SOURCE, PACKAGES, SOURCES, Package, closure, resolve

MANIFEST: Final = "engg-math.toml"
PYPROJECT: Final = "pyproject.toml"
DEFAULT_PYTHON: Final = ">=3.11"
ANY_VERSION: Final = "*"
_KEYS: Final = {"project", "python", "source", "modules"}
_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class Manifest:
    """Validated contents of ``engg-math.toml``."""

    project: str
    python: str = DEFAULT_PYTHON
    source: str = DEFAULT_SOURCE
    modules: dict[str, str] = field(default_factory=dict)


def find_root(start: Path | None = None) -> Path:
    """Return the nearest directory at or above ``start`` containing the manifest."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / MANIFEST).is_file():
            return directory
    raise ConfigError(f"no {MANIFEST} in {here} or its parents; run `engg-math init <name>`")


def _specifier(text: str, where: str) -> None:
    try:
        SpecifierSet(text)
    except InvalidSpecifier as exc:
        raise ConfigError(
            f"{MANIFEST}: {where} is not a valid version specifier: {text!r}"
        ) from exc


def validate(raw: dict[str, Any]) -> Manifest:
    """Check the manifest schema and return it as a `Manifest`."""
    unknown = sorted(set(raw) - _KEYS)
    if unknown:
        raise ConfigError(f"{MANIFEST}: unknown keys {unknown}; allowed: {sorted(_KEYS)}")
    project = raw.get("project")
    if not isinstance(project, str) or not _NAME.match(project):
        raise ConfigError(f"{MANIFEST}: `project` must be a name like 'my-workspace'")
    python = raw.get("python", DEFAULT_PYTHON)
    if not isinstance(python, str):
        raise ConfigError(f"{MANIFEST}: `python` must be a string such as '{DEFAULT_PYTHON}'")
    _specifier(python, "`python`")
    source = raw.get("source", DEFAULT_SOURCE)
    if source not in SOURCES:
        raise ConfigError(f"{MANIFEST}: `source` must be one of {list(SOURCES)}, got {source!r}")
    modules_raw = raw.get("modules", {})
    if not isinstance(modules_raw, dict):
        raise ConfigError(f"{MANIFEST}: `modules` must be a table of name = version")
    modules: dict[str, str] = {}
    for name, constraint in modules_raw.items():
        pkg = resolve(name)  # raises UnknownPackageError for typos
        if not isinstance(constraint, str):
            raise ConfigError(f"{MANIFEST}: modules.{name} must be a string")
        if constraint != ANY_VERSION:
            _specifier(constraint, f"modules.{name}")
        modules[pkg.name] = constraint
    return Manifest(project, python, source, modules)


def load(root: Path) -> Manifest:
    """Read and validate the manifest in ``root``."""
    path = root / MANIFEST
    try:
        raw = tomlkit.parse(path.read_text(encoding="utf-8")).unwrap()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except tomlkit.exceptions.TOMLKitError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    return validate(raw)


def save(root: Path, manifest: Manifest) -> None:
    """Write the manifest, modules sorted for stable diffs."""
    doc = tomlkit.document()
    doc.add("project", manifest.project)
    doc.add("python", manifest.python)
    doc.add("source", manifest.source)
    doc.add(tomlkit.nl())
    modules = tomlkit.table()
    for name in sorted(manifest.modules):
        modules.add(name, manifest.modules[name])
    doc.add("modules", modules)
    (root / MANIFEST).write_text(tomlkit.dumps(doc), encoding="utf-8")


# ----------------------------------------------------------------------- pyproject.toml


def new_pyproject(manifest: Manifest) -> str:
    """Return the initial workspace ``pyproject.toml``."""
    doc = tomlkit.document()
    project = tomlkit.table()
    project.add("name", manifest.project)
    project.add("version", "0.1.0")
    project.add("requires-python", manifest.python)
    project.add("dependencies", tomlkit.array())
    doc.add("project", project)
    return tomlkit.dumps(doc)


def _source_entry(pkg: Package) -> Any:  # noqa: ANN401 - tomlkit inline table
    entry = tomlkit.inline_table()
    entry.append("git", pkg.git.url)
    if pkg.git.subdirectory:
        entry.append("subdirectory", pkg.git.subdirectory)
    entry.append("rev", pkg.git.rev)
    return entry


def _requirement(pkg: Package, constraint: str) -> str:
    return pkg.dist if constraint == ANY_VERSION else f"{pkg.dist}{constraint}"


def sync_pyproject(root: Path, manifest: Manifest) -> None:
    """Rewrite the ecosystem dependencies and git sources of ``pyproject.toml`` from the manifest.

    Non-ecosystem dependencies and other tables are left untouched.
    """
    path = root / PYPROJECT
    if not path.is_file():
        raise ConfigError(f"{path} not found; `engg-math init` creates it")
    doc: Any = tomlkit.parse(path.read_text(encoding="utf-8"))
    project = doc.setdefault("project", tomlkit.table())
    eco = {p.dist for p in PACKAGES}
    kept = [d for d in project.get("dependencies", []) if _dist_of(d) not in eco]
    wanted = [_requirement(resolve(n), c) for n, c in sorted(manifest.modules.items())]
    deps = tomlkit.array()
    deps.multiline(True)
    for item in [*kept, *wanted]:
        deps.append(item)
    project["dependencies"] = deps

    tool = doc.setdefault("tool", tomlkit.table())
    uv = tool.setdefault("uv", tomlkit.table())
    sources = uv.get("sources", tomlkit.table())
    for dist in [k for k in sources if canonicalize_name(k) in eco]:
        del sources[dist]
    if manifest.source == "git":
        needed = {p.dist: p for name in manifest.modules for p in closure(name)}
        for dist in sorted(needed):
            sources[dist] = _source_entry(needed[dist])
    if sources:
        uv["sources"] = sources
    elif "sources" in uv:
        del uv["sources"]
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def declared_ecosystem_deps(root: Path) -> set[str]:
    """Canonical names of ecosystem dependencies declared in the workspace ``pyproject.toml``."""
    path = root / PYPROJECT
    if not path.is_file():
        return set()
    deps = tomlkit.parse(path.read_text(encoding="utf-8")).unwrap().get("project", {})
    eco = {p.dist for p in PACKAGES}
    return {n for d in deps.get("dependencies", []) if (n := _dist_of(d)) in eco}


def _dist_of(requirement: str) -> str:
    try:
        return canonicalize_name(Requirement(requirement).name)
    except InvalidRequirement:
        return requirement
