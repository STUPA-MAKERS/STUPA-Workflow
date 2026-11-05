---
id: "000343"
title: A file name is cleaned
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# A file name is cleaned

The display name keeps Unicode, but loses the path, control characters and bidi characters.
Every download header encodes it safely.
