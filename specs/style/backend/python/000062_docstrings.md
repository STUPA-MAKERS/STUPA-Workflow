---
id: "000062"
title: Docstrings instead of comments
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/
scope:
  - backend/
---

# Docstrings instead of comments

Every public module, class and function in `app/`, `worker/`, `scripts/` and `migrations/` must
have a Google-style docstring. A `#` comment in a code body must be only for a trick that the
code cannot show. The reason must go into the docstring.

Test: ruff rule set `D` with the Google convention.
