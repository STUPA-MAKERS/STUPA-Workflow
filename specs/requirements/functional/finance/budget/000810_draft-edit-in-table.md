---
id: "000810"
title: A draft is edited in the table
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
---

# A draft is edited in the table

On a wide screen, the column Ansatz of a draft must show one amount field in each row that
has no child. A press on a row must select its Kostenstelle, and the detail must show the
fields Ansatz and Erläuterung. On a phone a press on a row must open a bottom sheet with
these fields and the table must not show fields. Each field must be read-only when the
version is not in `draft`.

Reason: A plan has many lines, and one sheet for each amount costs too many steps. The
Ansatz of a parent is the sum of its children.
