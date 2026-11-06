---
id: "000269"
title: An applicant session can edit
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/service/edits.py
  - backend/app/modules/applications/service/service_base.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# An applicant session can edit

A magic link must open an applicant session that can edit. Each action must check the current
state: a data edit must answer 409 in a state without `edit_allowed`. Applicant transitions and
uploads must work in every state.
