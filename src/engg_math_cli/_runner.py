"""Subprocess boundary; tests substitute a fake `Runner`."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ._errors import ToolchainError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of a finished process."""

    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """Runs an external program to completion."""

    def run(self, args: Sequence[str], cwd: Path | None = None) -> RunResult:
        """Run ``args`` in ``cwd`` and capture its output."""
        ...


class SubprocessRunner:
    """Real process execution without a shell."""

    def run(self, args: Sequence[str], cwd: Path | None = None) -> RunResult:
        """Run ``args``; a missing executable raises `ToolchainError`."""
        try:
            done = subprocess.run(  # noqa: S603 - argument list, never a shell string
                list(args), cwd=cwd, capture_output=True, text=True, check=False
            )
        except FileNotFoundError as exc:
            raise ToolchainError(f"`{args[0]}` not found on PATH") from exc
        return RunResult(done.returncode, done.stdout, done.stderr)


def require_success(result: RunResult, action: str) -> RunResult:
    """Return ``result`` or raise `ToolchainError` carrying the tail of stderr."""
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise ToolchainError(f"{action} failed (exit {result.returncode}):\n{tail}")
    return result
