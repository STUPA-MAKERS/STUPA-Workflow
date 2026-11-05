---
id: "000084"
title: A value is not mutated
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
---

# A value is not mutated

Do not change a value in place: no `.append`, `.add`, `.update`, `x[k] = v` or `del` in
Python, no `.push`, `.splice`, in-place `.sort()`, `delete` or `Object.assign` onto an existing
object in TypeScript. Build the new value whole.
