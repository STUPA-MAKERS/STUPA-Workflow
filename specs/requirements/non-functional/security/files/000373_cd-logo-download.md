---
id: "000373"
title: A CD logo is served as a download
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/cd_logos.py
  - backend/app/modules/admin/router.py
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A CD logo is served as a download

A CD logo can be SVG or PDF, because only the render service reads it. Its file route must
answer `application/octet-stream` with `Content-Disposition: attachment`. The square slot is
the exception: it must accept only PNG, JPEG or WebP, and it is served inline.
