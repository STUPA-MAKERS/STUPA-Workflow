---
id: "000173"
title: Public pages are not indexed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# Public pages are not indexed

Every public protocol page and its PDF send `noindex` (meta robots and `X-Robots-Tag`).
