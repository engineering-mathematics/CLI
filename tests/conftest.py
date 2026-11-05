"""Shared fixtures: a scripted runner so no test starts a real process."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from engg_math_cli._runner import RunResult

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


@dataclass
class FakeRunner:
    """Records calls; ``respond`` maps a command to a result (default: success, no output)."""

    respond: Callable[[Sequence[str]], RunResult] = lambda _args: RunResult(0, "", "")
    calls: list[list[str]] = field(default_factory=list)

    def run(self, args: Sequence[str], cwd: Path | None = None) -> RunResult:
        self.calls.append(list(args))
        return self.respond(args)


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()
