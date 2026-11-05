---
id: "000067"
title: Commands run in the Nix dev shell
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - .
---

# Commands run in the Nix dev shell

Run backend, frontend, MCP and typst commands in the dev shell of the root flake, for example
`nix develop .#backend -c pytest`. Do not set `LD_LIBRARY_PATH` by hand.

Reason: Outside the shell, greenlet and libmagic are missing.
