---
id: "000372"
title: Branding logos are checked by their bytes
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Branding logos are checked by their bytes

A branding logo must be PNG, JPEG, WebP or ICO by its bytes, at most 2 MB. Inline SVG is
refused. A footer or legal URL must not use `javascript:`, `data:` or `vbscript:`.
