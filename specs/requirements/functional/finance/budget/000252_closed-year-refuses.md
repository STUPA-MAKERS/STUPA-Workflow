---
id: "000252"
title: A closed fiscal year refuses money changes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/fiscal_years.py
scope:
  - backend/app/modules/budget
---

# A closed fiscal year refuses money changes

In a closed fiscal year, every booking, transfer, allocation, move of an Antrag and revert must
answer 409 `fiscal_year_closed`. A closed year must not be deletable and must never be the
default year.
