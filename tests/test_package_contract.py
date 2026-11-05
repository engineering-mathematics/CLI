"""Package contract (the CLI lives outside the ``engg_math`` namespace)."""

from __future__ import annotations

import importlib
import importlib.resources
import pkgutil

import engg_math_cli as pkg


def test_package_is_marked_typed() -> None:
    assert importlib.resources.files(pkg).joinpath("py.typed").is_file()


def test_all_is_defined_and_resolvable() -> None:
    assert pkg.__all__, "public API must be declared via __all__"
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"__all__ lists missing name {name!r}"


def test_every_module_imports_cleanly() -> None:
    for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg.__name__}."):
        importlib.import_module(info.name)
