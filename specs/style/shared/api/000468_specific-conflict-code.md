---
id: "000468"
title: A conflict names a specific code
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/shared/errors.py
scope:
  - backend/app/shared/errors.py
  - backend/app/modules
---

# A conflict names a specific code

Every `ConflictError` must pass a `code=` argument. A new conflict must use a specific code,
not the generic `conflict`.

Reason: A client can only react to a conflict that it can tell apart.

Test: `backend/tests/unit/shared/test_conflict_codes.py`.
