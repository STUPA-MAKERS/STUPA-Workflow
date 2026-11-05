---
id: "000264"
title: An invoice file is served as a download
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
---

# An invoice file is served as a download

An invoice file is served as `application/pdf` with `Content-Disposition: attachment`. The
server ignores the MIME type from the client.

Reason: A PDF polyglot must not render in the origin of the app.
