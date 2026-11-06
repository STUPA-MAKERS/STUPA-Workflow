---
id: "000167"
title: Storage names replace non-ASCII characters
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/shared/filenames.py
scope:
  - backend/app/modules/files
  - frontend/src/app/shared
---

# Storage names replace non-ASCII characters

The storage name in the object key must replace umlauts and other non-ASCII characters with
`_`. The display name must keep them.
