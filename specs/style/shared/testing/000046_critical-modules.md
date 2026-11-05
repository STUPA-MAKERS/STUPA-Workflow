---
id: "000046"
title: Critical modules have full branch coverage
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/
---

# Critical modules have full branch coverage

The modules `auth`, `voting`, `flow`, `budget`, `webhooks`, `audit` and `backup` must have
100 % branch coverage. A change in one of them gets a security review before the merge.

Test: `backend/scripts/coverage_critical.py`
