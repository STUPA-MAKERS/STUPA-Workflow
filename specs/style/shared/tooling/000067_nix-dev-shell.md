---
id: "000067"
title: Commands run in the Nix dev shell
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - .
---

# Commands run in the Nix dev shell

Backend, frontend, MCP and typst commands must run in the dev shell of the root flake, for
example `nix develop .#backend -c pytest`. Nobody must set `LD_LIBRARY_PATH` by hand.

Reason: Outside the shell, greenlet and libmagic are missing.
