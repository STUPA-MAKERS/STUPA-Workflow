---
id: "000125"
title: An unconfirmed guest Antrag rests
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/service/create.py
  - backend/app/modules/applications/access.py
  - backend/worker/deadlines.py
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# An unconfirmed guest Antrag rests

A guest Antrag must stay invisible until the applicant confirms the e-mail. Until then the flow
routes must answer 404, the cron must skip it and no mail must go out for it. The confirmation
must start the flow exactly once.
