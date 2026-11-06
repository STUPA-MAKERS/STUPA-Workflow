---
id: "000178"
title: Downloads stream through the API
kind: non-functional
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

# Downloads stream through the API

The browser must not get a presigned MinIO URL. Every download must stream through an API
route that checks the access of the caller.

Reason: A presigned URL works for everyone who has it, and the API cannot revoke it.
