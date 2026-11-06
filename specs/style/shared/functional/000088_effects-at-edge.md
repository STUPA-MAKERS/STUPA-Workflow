---
id: "000088"
title: Effects stay at the edge
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - mcp/
  - typst/typst_service/
---

# Effects stay at the edge

Database, Redis, S3, mail, audit and WebSocket calls must stay in services, routers and Angular
services. The decision logic must be a pure function next to them.
