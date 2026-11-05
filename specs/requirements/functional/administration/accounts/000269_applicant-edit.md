---
id: "000269"
title: An applicant session can edit
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# An applicant session can edit

Every new magic link and applicant session has the scope `edit`. Each action checks the
current state: a data edit answers 409 in a state without `edit_allowed`. Applicant
transitions and uploads work in every state.
