---
id: "001273"
title: The activity page hides the own actions by default
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
implementation: null
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# The activity page hides the own actions by default

The page must hide by default the events whose actor is the person. A filter chip "Auch
eigene" must show them. The choice must stay for the next visit of the same browser.

Reason: The page answers what others did on the items of the person; the own actions stay one
tap away.
