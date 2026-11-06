---
id: "000062"
title: Docstrings instead of comments
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/
---

# Docstrings instead of comments

Every public module, class and function in `app/`, `worker/`, `scripts/` and `migrations/`
has a Google-style docstring. A `#` comment in a code body is only for a trick that the code
cannot show. The reason goes into the docstring.

Test: ruff rule set `D` with the Google convention.
