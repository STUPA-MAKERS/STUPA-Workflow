---
id: "000252"
title: A closed fiscal year refuses money changes
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
---

# A closed fiscal year refuses money changes

In a closed fiscal year, every booking, transfer, allocation, move of an Antrag and revert
answers 409 `fiscal_year_closed`. A closed year cannot be deleted and is never the default
year.
