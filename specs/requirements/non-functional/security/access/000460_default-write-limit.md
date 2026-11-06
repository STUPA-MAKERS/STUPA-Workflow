---
id: "000460"
title: Writes have a default rate limit
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/middleware.py
  - backend/app/settings.py
---

# Writes have a default rate limit

Every write without its own limit must count against `rl_default_write_per_hour` (100) per IP,
or `rl_default_write_session_per_hour` (3000) per session. Over the limit it must answer 429
with `Retry-After`.
