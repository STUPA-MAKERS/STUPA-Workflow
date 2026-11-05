---
id: "000269"
title: An applicant session can edit
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# An applicant session can edit

A magic link opens an applicant session that can edit. Each action checks the current state: a data edit answers 409 in a state without `edit_allowed`. Applicant
transitions and uploads work in every state.
