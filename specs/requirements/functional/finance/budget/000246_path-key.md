---
id: "000246"
title: A cost centre has a stable path key
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
---

# A cost centre has a stable path key

A cost centre has a `key` and a server-made `path_key`, for example `VS-800-04`. The `key` and
the parent of a cost centre do not change. Only a top-level cost centre has a Gremium and a
fiscal start date.
