---
id: "000264"
title: An invoice file is served as a download
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/budget/tree_router.py
  - backend/app/modules/budget/tree/invoices.py
scope:
  - backend/app/modules/budget
---

# An invoice file is served as a download

An invoice file must be served as `application/pdf` with `Content-Disposition: attachment`. The
server must ignore the MIME type from the client. The only exception is the sandboxed inline
preview of 001083 with `?inline=true`.

Reason: A PDF polyglot must not render in the origin of the app. The `sandbox` of the preview
gives the file an opaque origin.
