---
id: "000335"
title: The avatar fetch is fixed and limited
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/avatars
scope:
  - backend/app/modules/avatars
---

# The avatar fetch is fixed and limited

The avatar fetch goes only to `gravatar.com` through the SSRF guard, follows no redirect and
reads at most 512 KiB. The answer must be PNG, JPEG, GIF or WebP by its bytes, never SVG.
