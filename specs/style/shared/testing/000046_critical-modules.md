---
id: "000046"
title: Critical modules have full branch coverage
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/scripts/coverage_critical.py
  - .github/workflows/ci.yml
scope:
  - backend/app/modules/
---

# Critical modules have full branch coverage

The modules `auth`, `voting`, `flow`, `budget`, `webhooks`, `audit` and `backup`, the files of the
applicant login in `applications` (000649), and the files `app/shared/ssrf.py` and
`worker/backup.py` must have 100 % branch coverage. The unit tests and the
integration tests count together for this value, as in 000045. A change in one of
them must get a security review before the merge.

Test: `backend/scripts/coverage_critical.py`
