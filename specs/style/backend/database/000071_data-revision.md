---
id: "000071"
title: A data change has its own revision
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/migrations/versions
scope:
  - backend/migrations/
---

# A data change has its own revision

A pure data migration or a constraint change must get its own revision. The `0001` baseline
must stay as it is.
