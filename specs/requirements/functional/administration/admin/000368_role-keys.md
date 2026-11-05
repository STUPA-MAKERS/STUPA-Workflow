---
id: "000368"
title: Role keys are fixed lower case
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Role keys are fixed lower case

A role key matches `^[a-z][a-z0-9_]*$` and never changes.
