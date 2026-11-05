---
id: "000339"
title: An attachment is at most 10 MiB
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# An attachment is at most 10 MiB

An attachment is at most 10 MiB. The server checks the size while it reads the stream and
finds the real MIME type from the bytes.
