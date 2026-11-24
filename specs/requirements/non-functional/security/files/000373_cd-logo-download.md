---
id: "000373"
title: A CD logo is served as a download
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/site_config/cd_logos.py
  - backend/app/modules/admin/router/cd_variants_router.py
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A CD logo is served as a download

A CD logo can be SVG or PDF, because only the render service reads it. Its file route must
answer `application/octet-stream` with `Content-Disposition: attachment`. The square slot is
the exception: it must accept only PNG, JPEG or WebP, and it is served inline. A PDF, PNG, JPEG
or WebP logo also has the sandboxed inline preview of 001083 with `?inline=true`, with its real
MIME type. An SVG logo has no preview.
