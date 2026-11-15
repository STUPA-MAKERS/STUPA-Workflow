---
id: "000372"
title: Branding logos are checked by their bytes
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/site_config/branding.py
scope:
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Branding logos are checked by their bytes

A branding logo that the browser shows must be PNG, JPEG, WebP or ICO by its bytes, at most
2 MB. Inline SVG is refused. The export logo and the footer graphic go to the render service
only and follow their own rules (000891, 000892). A footer or legal URL must not use `javascript:`, `data:` or `vbscript:`.
