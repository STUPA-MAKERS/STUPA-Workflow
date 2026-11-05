---
id: "000065"
title: A principal column is known to the account merge
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# A principal column is known to the account merge

A new column that holds a principal id or `sub` must have an entry in `SUB_COLUMNS` of
`app/modules/admin/principal_merge.py`.

Reason: The account merge rewrites only the columns it knows.

Test: the guard test of `principal_merge`.
