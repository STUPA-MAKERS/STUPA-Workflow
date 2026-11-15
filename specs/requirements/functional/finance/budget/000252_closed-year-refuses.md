---
id: "000252"
title: A closed fiscal year refuses money changes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/fiscal_years.py
scope:
  - backend/app/modules/budget
---

# A closed fiscal year refuses money changes

In a closed fiscal year, every booking, transfer, allocation, move of an Antrag into the year
and revert must answer 409 `fiscal_year_closed`. An Antrag can leave a closed year for an open
one (000991). A closed year must not be deletable and must never be the default year.
