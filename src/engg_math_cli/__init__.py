"""Workspace manager and health checker for the Engineering Mathematics ecosystem."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._app import app


def main() -> None:
    """Console-script entry point."""
    app()


try:
    __version__ = version("engg-math-cli")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "app", "main"]
