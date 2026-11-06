---
id: "000264"
title: An invoice file is served as a download
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget
scope:
  - backend/app/modules/budget
---

# An invoice file is served as a download

An invoice file must be served as `application/pdf` with `Content-Disposition: attachment`. The
server must ignore the MIME type from the client.

Reason: A PDF polyglot must not render in the origin of the app.
