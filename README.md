# engg-math-cli

`engg-math`: create Engineering Mathematics workspaces, add ecosystem packages by friendly name, and
check the environment. The libraries work without it, and this tool imports none of them.

```bash
pip install engg-math-cli
engg-math init my-lab && cd my-lab
engg-math add dynamical-systems
engg-math doctor
```

## Commands

| Command | Purpose |
|---|---|
| `init NAME [--python SPEC] [--source git\|pypi]` | New workspace: `engg-math.toml`, `pyproject.toml`, README |
| `add PACKAGE [--version SPEC] [--no-sync]` | Add a package; `uv` installs it |
| `remove PACKAGE [--no-sync]` | Remove a package and prune its unused sources |
| `update [--no-sync]` | Re-pin sources to the revisions this CLI knows and upgrade the lock |
| `list [--available]` | Workspace packages, or every known package |
| `info PACKAGE` | Summary, requirements, dependents |
| `graph` | Dependency tree of the workspace |
| `doctor [--audit]` | Python, `uv`, manifest, installed versions and compatibility, BLAS/LAPACK, advisories |

Package names resolve from any spelling: `linear-systems`, `linear_systems`, `engg-math-linear-systems`,
`engg_math.linear_systems`. Typos get suggestions.

## Conventions

- **Manifest.** `engg-math.toml` holds `project`, `python`, `source` and a `[modules]` table. It is validated;
  unknown keys and invalid specifiers are errors. `pyproject.toml` is derived from it.
- **Sources.** Until the first PyPI release, `source = "git"` pins every package to a commit and repeats the
  git source of each transitive dependency (`uv` sources do not propagate). `source = "pypi"` installs normally.
- **Output.** `--json` prints a stable envelope (`schema`, `ok`, `command`, `data` or `error`). `NO_COLOR` is
  honoured and styling is dropped when stdout is not a terminal. Nothing animates.
- **Exit codes.** 0 success; 1 failed check or other error; 2 invalid or missing manifest; 3 unknown package;
  4 `uv` missing or failed.

## Development

```bash
uv sync
uv run pytest && uv run ruff check && uv run mypy && uv run lint-imports
```

Licensed under Apache-2.0.
