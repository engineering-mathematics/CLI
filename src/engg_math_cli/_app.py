"""Typer application: command wiring, error handling and exit codes."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, ParamSpec, TypeVar

import typer
from rich.tree import Tree

from . import _install as inst
from . import _workspace as ws
from ._doctor import as_dicts, run_doctor
from ._errors import CliError, ConfigError, ToolchainError
from ._output import Output
from ._registry import DEFAULT_SOURCE, PACKAGES, SOURCES, closure, dependents, resolve
from ._runner import Runner, SubprocessRunner

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")

EXIT_UNHEALTHY: Final = 1

app = typer.Typer(
    name="engg-math",
    help="Create and manage Engineering Mathematics workspaces.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


class State:
    """Per-invocation settings shared through the Typer context."""

    def __init__(self, *, json_mode: bool, runner: Runner) -> None:
        self.out = Output(json_mode=json_mode)
        self.runner = runner


def _state(ctx: typer.Context) -> State:
    state: State = ctx.obj
    return state


def guarded(func: Callable[P, R]) -> Callable[P, R]:
    """Turn `CliError` into a message and exit code instead of a traceback."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        ctx: typer.Context = kwargs["ctx"]  # type: ignore[assignment]
        try:
            return func(*args, **kwargs)
        except CliError as exc:
            _state(ctx).out.fail(ctx.info_name or "engg-math", exc, exc.exit_code)
            raise typer.Exit(exc.exit_code) from exc

    return wrapper


def _version(value: bool) -> None:
    if value:
        from importlib.metadata import version  # noqa: PLC0415

        typer.echo(version("engg-math-cli"))
        raise typer.Exit


@app.callback()
def _root(
    ctx: typer.Context,
    json_mode: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    _version_flag: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    ctx.obj = ctx.obj or State(json_mode=json_mode, runner=SubprocessRunner())
    if isinstance(ctx.obj, State):
        ctx.obj.out.json_mode = json_mode


Sync = Annotated[bool, typer.Option("--sync/--no-sync", help="Run `uv sync` afterwards.")]


@app.command()
@guarded
def init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Workspace (and directory) name.")],
    python: Annotated[str, typer.Option(help="Python version constraint.")] = ws.DEFAULT_PYTHON,
    source: Annotated[
        str, typer.Option(help=f"Where packages come from: {', '.join(SOURCES)}.")
    ] = DEFAULT_SOURCE,
) -> None:
    """Create a workspace: engg-math.toml, pyproject.toml and a README."""
    state = _state(ctx)
    root = inst.init_workspace(Path.cwd(), name, python, source)
    if state.out.json_mode:
        state.out.emit("init", {"root": str(root), "project": name})
    else:
        state.out.line(f"[ok]created[/ok] {root}\nnext: cd {name} && engg-math add linear-systems")


@app.command()
@guarded
def add(
    ctx: typer.Context,
    package: Annotated[str, typer.Argument(help="e.g. linear-systems")],
    version: Annotated[
        str, typer.Option(help="Version specifier, e.g. '>=0.1,<0.2'.")
    ] = ws.ANY_VERSION,
    sync: Sync = True,
) -> None:
    """Add a package (and, from git, its dependencies) to the workspace."""
    state = _state(ctx)
    root = ws.find_root()
    dists = inst.add_module(root, package, version, state.runner if sync else None)
    if state.out.json_mode:
        state.out.emit(
            "add", {"package": resolve(package).name, "installed": dists, "synced": sync}
        )
    else:
        state.out.line(f"[ok]added[/ok] {resolve(package).dist} ({len(dists)} distribution(s))")


@app.command()
@guarded
def remove(
    ctx: typer.Context,
    package: Annotated[str, typer.Argument(help="Package to remove.")],
    sync: Sync = True,
) -> None:
    """Remove a package from the workspace."""
    state = _state(ctx)
    inst.remove_module(ws.find_root(), package, state.runner if sync else None)
    if state.out.json_mode:
        state.out.emit("remove", {"package": resolve(package).name, "synced": sync})
    else:
        state.out.line(f"[ok]removed[/ok] {resolve(package).dist}")


@app.command()
@guarded
def update(ctx: typer.Context, sync: Sync = True) -> None:
    """Re-pin ecosystem sources to the revisions known to this CLI and upgrade the lock."""
    state = _state(ctx)
    inst.update_workspace(ws.find_root(), state.runner if sync else None)
    if state.out.json_mode:
        state.out.emit("update", {"synced": sync})
    else:
        state.out.line("[ok]updated[/ok]")


@app.command(name="list")
@guarded
def list_(
    ctx: typer.Context,
    available: Annotated[
        bool, typer.Option("--available", help="List all known packages.")
    ] = False,
) -> None:
    """List the workspace's packages, or every known package with --available."""
    state = _state(ctx)
    if available:
        rows = [[p.name, p.dist, p.summary] for p in PACKAGES]
        data = [{"name": p.name, "dist": p.dist, "summary": p.summary} for p in PACKAGES]
    else:
        manifest = ws.load(ws.find_root())
        rows = [[n, resolve(n).dist, c] for n, c in sorted(manifest.modules.items())]
        data = [
            {"name": n, "dist": resolve(n).dist, "version": c}
            for n, c in sorted(manifest.modules.items())
        ]
    if state.out.json_mode:
        state.out.emit("list", data)
    else:
        state.out.table("Packages", ["name", "dist", "summary" if available else "version"], rows)


@app.command()
@guarded
def info(ctx: typer.Context, package: Annotated[str, typer.Argument()]) -> None:
    """Show a package's summary, requirements and dependents."""
    state = _state(ctx)
    pkg = resolve(package)
    data = {
        "name": pkg.name,
        "dist": pkg.dist,
        "summary": pkg.summary,
        "requires": list(pkg.requires),
        "required_by": [p.name for p in dependents(pkg.name)],
        "git": {"url": pkg.git.url, "rev": pkg.git.rev, "subdirectory": pkg.git.subdirectory},
    }
    if state.out.json_mode:
        state.out.emit("info", data)
        return
    state.out.line(f"[name]{pkg.dist}[/name]\n{pkg.summary}")
    state.out.line(f"requires:    {', '.join(pkg.requires) or '-'}")
    state.out.line(f"required by: {', '.join(data['required_by']) or '-'}")


@app.command()
@guarded
def graph(ctx: typer.Context) -> None:
    """Show the workspace's packages with their dependencies."""
    state = _state(ctx)
    manifest = ws.load(ws.find_root())
    data: dict[str, Any] = {n: [p.name for p in closure(n)[:-1]] for n in sorted(manifest.modules)}
    if state.out.json_mode:
        state.out.emit("graph", data)
        return
    tree = Tree(f"[name]{manifest.project}[/name]")
    for name in data:
        _grow(tree.add(name), resolve(name).requires)
    state.out.out.print(tree)


def _grow(node: Tree, requires: tuple[str, ...]) -> None:
    for dep in requires:
        _grow(node.add(dep), resolve(dep).requires)


@app.command()
@guarded
def doctor(
    ctx: typer.Context,
    audit: Annotated[
        bool, typer.Option("--audit", help="Query vulnerability advisories (network).")
    ] = False,
) -> None:
    """Check the toolchain, workspace and installed packages."""
    state = _state(ctx)
    checks = run_doctor(None, state.runner, audit=audit)
    failed = any(c.status == "fail" for c in checks)
    if state.out.json_mode:
        state.out.emit("doctor", {"healthy": not failed, "checks": as_dicts(checks)})
    else:
        style = {"ok": "ok", "warn": "warn", "fail": "fail", "skip": "dim"}
        state.out.table(
            "engg-math doctor",
            ["check", "status", "detail"],
            [
                [c.name, f"[{style[c.status]}]{c.status}[/{style[c.status]}]", c.detail]
                for c in checks
            ],
        )
    if failed:
        raise typer.Exit(EXIT_UNHEALTHY)


__all__ = ["ConfigError", "ToolchainError", "app"]
