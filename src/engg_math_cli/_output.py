"""Presentation: human output through Rich, machine output as stable JSON.

JSON envelope: ``{"schema": 1, "ok": bool, "command": str, "data": ...}`` on success and
``{"schema": 1, "ok": false, "command": str, "error": {...}}`` on failure.
Rich honours ``NO_COLOR`` and strips styling when stdout is not a terminal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final

from rich.console import Console
from rich.table import Table
from rich.theme import Theme

SCHEMA_VERSION: Final = 1
THEME: Final = Theme(
    {"ok": "green", "warn": "yellow", "fail": "red bold", "dim": "dim", "name": "cyan"}
)


@dataclass(slots=True)
class Output:
    """Writes results to stdout and errors to stderr in the selected format."""

    json_mode: bool = False
    out: Console = field(default_factory=lambda: Console(theme=THEME, highlight=False))
    err: Console = field(default_factory=lambda: Console(theme=THEME, highlight=False, stderr=True))

    def emit(self, command: str, data: Any) -> None:  # noqa: ANN401 - JSON-serialisable payload
        """Write the JSON envelope; only used in JSON mode."""
        envelope = {"schema": SCHEMA_VERSION, "ok": True, "command": command, "data": data}
        self.out.print_json(json.dumps(envelope), highlight=False)

    def fail(self, command: str, error: Exception, exit_code: int) -> None:
        """Report an error in the selected format."""
        if self.json_mode:
            detail = {"type": type(error).__name__, "message": str(error), "exit_code": exit_code}
            envelope = {"schema": SCHEMA_VERSION, "ok": False, "command": command, "error": detail}
            self.out.print_json(json.dumps(envelope), highlight=False)
        else:
            self.err.print(f"[fail]error:[/fail] {error}", markup=True, soft_wrap=True)

    def line(self, text: str) -> None:
        """Print a human line (no-op in JSON mode)."""
        if not self.json_mode:
            self.out.print(text, soft_wrap=True)

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        """Print a table (no-op in JSON mode)."""
        if self.json_mode:
            return
        table = Table(title=title, title_justify="left", header_style="bold")
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*row)
        self.out.print(table)
