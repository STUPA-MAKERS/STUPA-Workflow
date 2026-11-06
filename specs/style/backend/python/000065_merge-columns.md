---
id: "000065"
title: A principal column is known to the account merge
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/
scope:
  - backend/app/
---

# A principal column is known to the account merge

A new column that holds a principal id or `sub` must have an entry in `SUB_COLUMNS` of
`app/modules/admin/principal_merge.py`.

Reason: The account merge rewrites only the columns it knows.

Test:
`backend/tests/unit/modules/admin/test_principal_merge_guard.py:test_every_principal_column_has_a_merge_rule`.
