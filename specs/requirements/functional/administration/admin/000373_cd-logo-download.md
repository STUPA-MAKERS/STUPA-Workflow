---
id: "000373"
title: A CD logo is served only as a download
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A CD logo is served only as a download

A CD logo can be SVG or PDF, because only the render service reads it. Its file route answers
`application/octet-stream` with `Content-Disposition: attachment`.
