"""Exception types. Each carries the process exit code the CLI reports."""

from __future__ import annotations


class CliError(Exception):
    """Base class for failures the CLI reports without a traceback."""

    exit_code = 1


class ConfigError(CliError):
    """``engg-math.toml`` is missing, unreadable or invalid."""

    exit_code = 2


class UnknownPackageError(CliError):
    """A name does not resolve to an ecosystem package."""

    exit_code = 3


class ToolchainError(CliError):
    """``uv`` is missing or a ``uv`` invocation failed."""

    exit_code = 4
