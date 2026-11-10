---
id: "000644"
title: The shared code imports no module
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/shared
  - backend/app/db.py
  - backend/app/settings.py
  - backend/app/logging_config.py
  - backend/pyproject.toml
---

# The shared code imports no module

The code in `backend/app/shared` and the files `db.py`, `settings.py` and `logging_config.py` in
`backend/app` must not import from `backend/app/modules`.

Reason: Every module imports the shared code. An import in the other direction ties every
module to the module that the shared code imports.

Test: The import contract in `backend/pyproject.toml`, which the CI job `be-lint` checks with
`lint-imports`.
