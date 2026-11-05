---
id: "000088"
title: Effects stay at the edge
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
---

# Effects stay at the edge

Database, Redis, S3, mail, audit and WebSocket calls stay in services, routers and Angular
services. The decision logic is a pure function next to them.
