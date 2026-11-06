---
id: "000368"
title: Role keys are fixed lower case
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Role keys are fixed lower case

A role key must match `^[a-z][a-z0-9_]*$` and must never change.
