---
name: nix-dev-shells
description: Run every dev command in a devShell of the root flake.nix. Do not patch LD_LIBRARY_PATH by hand
metadata:
  node_type: memory
  type: feedback
---

Run every development command inside a Nix devShell from the root `flake.nix`:
`nix develop .#backend | .#frontend | .#mcp | .#admin-cli | .#typst`, or `.#default` for the
whole monorepo (Node plus Python).

The Python shells (`backend`, `mcp`, `admin-cli`, `typst`) give you Python 3.13, `uv`, `ruff`
and `basedpyright`, and export `LD_LIBRARY_PATH` with `libstdc++` (greenlet, which SQLAlchemy
loads on every async call) and `libmagic` (`python-magic`, the MIME sniff on every upload).
`backend` and `admin-cli` add `postgresql`; `typst` adds the typst CLI and `poppler-utils`.
The `frontend` shell gives you Node 22.

**Why:** the toolchain outside the shell is incomplete. Without it `pytest` fails with "the
greenlet library is required" and "failed to find libmagic". A manual `LD_LIBRARY_PATH`
assignment also breaks the Nix binaries in the same shell, which is why the flake appends to
the variable. Never hand-patch `LD_LIBRARY_PATH`; fix `flake.nix` instead.

**How to apply:** prefix commands with `nix develop .#<component> -c <cmd>`. The `shellHook`
starts zsh only in an interactive shell (`[[ $- == *i* ]]`), so `-c` is safe in scripts. A
pip-installed `basedpyright` inside `.venv` shadows the Nix one, so resolve the binary BEFORE
you activate a virtualenv, or call it through `nix develop -c`.

The frontend needs the `frontend/vendor/ui-kit` git submodule (`git submodule update
--init`), and the typst service needs its `hsrtreport-typst` submodule. The Nix `frontend`
package output copies the pinned `ui-kit` flake input in instead.
