"""Name resolution and the package table."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from engg_math_cli._errors import UnknownPackageError
from engg_math_cli._registry import PACKAGES, closure, dependents, normalize, resolve

NAMES = [p.name for p in PACKAGES]


@pytest.mark.parametrize(
    "spelling",
    [
        "linear-systems",
        "linear_systems",
        "engg-math-linear-systems",
        "engg_math.linear_systems",
        "  Linear-Systems ",
    ],
)
def test_all_spellings_resolve_to_one_package(spelling: str) -> None:
    """REQ-CLI-001: friendly names resolve from every accepted spelling."""
    assert resolve(spelling).name == "linear-systems"


@given(st.sampled_from(NAMES), st.sampled_from(["-", "_", "."]), st.booleans())
def test_resolution_ignores_separator_and_prefix(name: str, sep: str, prefixed: bool) -> None:
    """REQ-CLI-002: separator style and the dist prefix never change the result."""
    text = name.replace("-", sep)
    if prefixed:
        text = "engg-math-" + text
    assert resolve(text).name == name


def test_unknown_name_suggests_close_matches() -> None:
    """REQ-CLI-003: a typo yields a suggestion and exit code 3."""
    with pytest.raises(UnknownPackageError, match="did you mean linear-systems") as info:
        resolve("linear-system")
    assert info.value.exit_code == 3


def test_unknown_name_without_suggestion() -> None:
    with pytest.raises(UnknownPackageError) as info:
        resolve("zzzzzz")
    assert "did you mean" not in str(info.value)


def test_normalize_is_idempotent() -> None:
    assert normalize(normalize("engg_math.Linear_Systems")) == "linear-systems"


def test_closure_lists_dependencies_first_without_duplicates() -> None:
    """REQ-CLI-004: dependency closure is topologically ordered."""
    names = [p.name for p in closure("optimization")]
    assert names[-1] == "optimization"
    assert len(names) == len(set(names))
    for position, name in enumerate(names):
        assert all(names.index(dep) < position for dep in resolve(name).requires)


def test_dependents_are_direct_only() -> None:
    assert {p.name for p in dependents("continuous-analysis")} == {"dynamical-systems"}


def test_registry_is_internally_consistent() -> None:
    """REQ-CLI-005: requirements exist, sources are pinned to full commits, no duplicates."""
    assert len(NAMES) == len(set(NAMES))
    for pkg in PACKAGES:
        assert set(pkg.requires) <= set(NAMES)
        assert re.fullmatch(r"[0-9a-f]{40}", pkg.git.rev), pkg.name
        assert pkg.dist == f"engg-math-{pkg.name}"
