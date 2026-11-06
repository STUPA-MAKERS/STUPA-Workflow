---
id: "000343"
title: A file name is cleaned
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# A file name is cleaned

The display name must keep Unicode, but it must lose the path, control characters and bidi
characters. Every download header must encode it safely.
