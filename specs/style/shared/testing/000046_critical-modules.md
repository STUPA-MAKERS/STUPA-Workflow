---
id: "000046"
title: Critical modules have full branch coverage
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/
---

# Critical modules have full branch coverage

The modules `auth`, `voting`, `flow`, `budget`, `webhooks`, `audit` and `backup` and the files
`app/shared/ssrf.py` and `worker/backup.py` must have 100 % branch coverage. A change in one of
them must get a security review before the merge.

Test: `backend/scripts/coverage_critical.py`
