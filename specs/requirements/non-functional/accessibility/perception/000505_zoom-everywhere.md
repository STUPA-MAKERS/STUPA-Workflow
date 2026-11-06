---
id: "000505"
title: Zoom is never blocked
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/index.html
  - frontend/src/app/core/pwa
---

# Zoom is never blocked

The viewport meta tag must not contain `user-scalable=no` or `maximum-scale`. This applies
in the browser tab and in the installed app.

Reason: WCAG 1.4.4. A person with low vision needs pinch zoom also in the installed app.

Test: `frontend/src/app/core/pwa/install-metadata.spec.ts`.
