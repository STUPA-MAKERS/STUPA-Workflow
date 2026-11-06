---
id: "000167"
title: Storage names replace non-ASCII characters
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/files
  - frontend/src/app/shared
---

# Storage names replace non-ASCII characters

The storage name in the object key replaces umlauts and other non-ASCII characters with `_`.
The display name keeps them.
