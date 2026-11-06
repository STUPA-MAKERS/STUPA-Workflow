---
id: "000439"
title: A merge combines duplicates and stops at a conflict
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth
  - backend/app/modules/admin
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# A merge combines duplicates and stops at a conflict

A merge must combine the duplicate rows of the two principals. A real conflict must block the
merge.
