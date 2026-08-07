---
name: nix-dev-shells
description: Use the Nix devShells for all development. Do not patch LD_LIBRARY_PATH by hand
metadata:
  node_type: memory
  type: feedback
---

Run every development command inside a Nix devShell. Both repos ship a `flake.nix`:

- **STUPA-Workflow** — `nix develop .#backend | .#frontend | .#mcp | .#admin-cli | .#pytex`, or
  `.#default` for the whole monorepo (Node plus Python).
- **PyTeX-Preprocessor** — its own flake with a devShell and a package output.

The shells give you `python 3.13`, `uv`, `ruff`, `basedpyright` and `node 22`. Every Python
shell also exports `LD_LIBRARY_PATH` with `libstdc++` (greenlet, which SQLAlchemy loads on
every async call) and `libmagic` (`python-magic`, the MIME sniff on every upload). The
`backend` shell adds `postgresql`.

**Why:** the toolchain outside the shell is incomplete. A bare shell made `ruff`,
`basedpyright`, `greenlet` and `python-magic` fail, and a manual `LD_LIBRARY_PATH` repair
then broke the Nix binaries themselves. The flake now appends instead of assigns, which
keeps both working. Never hand-patch `LD_LIBRARY_PATH` again — fix `flake.nix` instead.

**How to apply:** prefix commands with `nix develop .#<component> -c <cmd>`. The `shellHook`
guards its `exec zsh` with `[[ $- == *i* ]]`, so `-c` stays non-interactive and safe for
scripts. A pip-installed `basedpyright` inside `.venv` shadows the Nix one, so resolve the
binary BEFORE you activate a virtualenv, or just call it through `nix develop -c`.

The frontend needs the `frontend/vendor/ui-kit` git submodule
(`git submodule update --init`). The Nix `frontend` package output copies the pinned `ui-kit`
flake input in instead. See [[repo-ship-workflow]], [[work-autonomously]].
