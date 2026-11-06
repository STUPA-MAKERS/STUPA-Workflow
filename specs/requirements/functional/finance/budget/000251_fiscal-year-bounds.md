---
id: "000251"
title: A fiscal year starts on a day from 1 to 28
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/budget/tree_rules.py
scope:
  - backend/app/modules/budget
---

# A fiscal year starts on a day from 1 to 28

A top-level cost centre sets the start month and a start day from 1 to 28. Fiscal years of
one cost centre must not overlap. The label is `YYYY` for a start on 1 January, else
`YYYY/YY`.
