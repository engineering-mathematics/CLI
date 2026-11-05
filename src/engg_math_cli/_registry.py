"""Ecosystem packages, name resolution and pre-publication git sources.

Until the first PyPI release the libraries install from pinned git commits. ``uv`` sources do not
propagate to dependents, so installing a package means adding every package in its dependency
closure with its own source. Remove ``Package.git`` and ``DEFAULT_SOURCE = "git"`` after publishing.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Final

from ._errors import UnknownPackageError

ORG: Final = "https://github.com/engineering-mathematics"
INFRA_REV: Final = "ed62979978977e80bb25ef73e905fd28bab46c8e"
DIST_PREFIX: Final = "engg-math-"
DEFAULT_SOURCE: Final = "git"
SOURCES: Final = ("git", "pypi")


@dataclass(frozen=True, slots=True)
class GitSource:
    """A pinned git location for a distribution."""

    url: str
    rev: str
    subdirectory: str | None = None


@dataclass(frozen=True, slots=True)
class Package:
    """An installable ecosystem distribution."""

    name: str
    summary: str
    requires: tuple[str, ...]
    git: GitSource

    @property
    def dist(self) -> str:
        """PyPI distribution name."""
        return DIST_PREFIX + self.name


def _infra(name: str) -> GitSource:
    return GitSource(f"{ORG}/infrastructure", INFRA_REV, f"packages/{name}")


def _repo(name: str, rev: str) -> GitSource:
    return GitSource(f"{ORG}/{name}", rev)


PACKAGES: Final[tuple[Package, ...]] = (
    Package("core", "Shared configuration, error types and array contracts", (), _infra("core")),
    Package("units", "Shared unit registry and dimensional checking", (), _infra("units")),
    Package("viz", "Terminal rendering: theme, panels, JSON output", (), _infra("viz")),
    Package(
        "linear-systems",
        "Column-major, unit-aware dense and sparse linear algebra",
        ("core", "units"),
        _repo("linear-systems", "138b7d8e14389c0194c2b1746636fc19f2042059"),
    ),
    Package(
        "numerical-computation",
        "Root finding, differentiation, quadrature and interpolation",
        ("core", "linear-systems"),
        _repo("numerical-computation", "487661d11596b2e5087c4503fbeeb467cf58f149"),
    ),
    Package(
        "optimization",
        "Minimisation, least squares and linear programming",
        ("core", "linear-systems", "numerical-computation"),
        _repo("optimization", "dbc3d6537e605624dc275272e0c65b57f67b630b"),
    ),
    Package(
        "continuous-analysis",
        "Polynomials, transfer functions, state-space models and linear ODEs",
        ("core",),
        _repo("continuous-analysis", "12e44121d0e57cc0338535a9901a5d8fbb6cb34f"),
    ),
    Package(
        "dynamical-systems",
        "Time and frequency response, controllability and observability",
        ("core", "continuous-analysis", "linear-systems"),
        _repo("dynamical-systems", "f6d4ff5947eeaf23f27c3919af1d589abca90b1f"),
    ),
    Package(
        "discrete-structures",
        "Sets, combinatorics, Boolean logic and directed graphs",
        ("core",),
        _repo("discrete-structures", "96638f467626c15e4e682a0cc6f482315b53a2c6"),
    ),
    Package(
        "stochastic-systems",
        "Distributions and exact Bayesian-network inference",
        ("core", "discrete-structures"),
        _repo("stochastic-systems", "3b20b75e500acab761a058af83a4d6f2e48d8bfe"),
    ),
    Package(
        "transform-analysis",
        "FFT, spectral estimation and z-domain analysis",
        ("core",),
        _repo("transform-analysis", "ed4b949177a60fc10198affb6ccfb36703f2c2e3"),
    ),
)

_BY_NAME: Final = {p.name: p for p in PACKAGES}
_SEPARATORS: Final = re.compile(r"[-_.\s]+")


def normalize(name: str) -> str:
    """Reduce any accepted spelling to the short kebab-case name.

    Accepts ``linear-systems``, ``linear_systems``, ``engg-math-linear-systems`` and
    ``engg_math.linear_systems``.
    """
    key = _SEPARATORS.sub("-", name.strip().lower())
    return key.removeprefix(DIST_PREFIX)


def resolve(name: str) -> Package:
    """Return the package for ``name`` or raise `UnknownPackageError` with suggestions."""
    key = normalize(name)
    if key in _BY_NAME:
        return _BY_NAME[key]
    close = difflib.get_close_matches(key, _BY_NAME, n=3, cutoff=0.6)
    hint = f"; did you mean {', '.join(close)}?" if close else ""
    raise UnknownPackageError(f"unknown package {name!r}{hint}")


def closure(name: str) -> list[Package]:
    """Return ``name`` and everything it requires, dependencies first."""
    ordered: list[Package] = []

    def visit(pkg: Package) -> None:
        for dep in pkg.requires:
            visit(_BY_NAME[dep])
        if pkg not in ordered:
            ordered.append(pkg)

    visit(resolve(name))
    return ordered


def dependents(name: str) -> list[Package]:
    """Return the packages that directly require ``name``."""
    target = resolve(name).name
    return [p for p in PACKAGES if target in p.requires]
