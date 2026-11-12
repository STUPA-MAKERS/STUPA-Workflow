---
id: "000801"
title: A closed fiscal year refuses plan changes
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A closed fiscal year refuses plan changes

In a closed fiscal year, each write to the Haushaltsplan, its versions and its lines must
answer 409 `fiscal_year_closed`.

Reason: A plan change moves allocations, and a closed year refuses money changes.
