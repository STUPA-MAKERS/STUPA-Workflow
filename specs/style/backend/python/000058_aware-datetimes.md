---
id: "000058"
title: Datetimes are timezone-aware
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/
---

# Datetimes are timezone-aware

Every datetime must be timezone-aware: `timestamptz` in the database, `datetime.now(UTC)` in
Python. Do not use `utcnow()` or a naive datetime.

Reason: One naive value breaks every comparison it reaches.
