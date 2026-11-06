---
id: "000339"
title: An attachment is at most 10 MiB
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/files
  - backend/app/modules/media
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# An attachment is at most 10 MiB

An attachment must be at most 10 MiB. The server must check the size while it reads the stream,
and it must find the real MIME type from the bytes.
