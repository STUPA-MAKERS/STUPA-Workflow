---
id: "000246"
title: A cost centre has a stable path key
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/budget
---

# A cost centre has a stable path key

A cost centre must have a `key` and a server-made `path_key`, for example `VS-800-04`. The
`key` and the parent of a cost centre must not change. Only a top-level cost centre must have a
Gremium and a fiscal start date.
