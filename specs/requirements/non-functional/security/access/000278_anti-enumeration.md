---
id: "000278"
title: A magic-link request does not reveal accounts
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth/router.py
  - backend/app/modules/auth/service.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# A magic-link request does not reveal accounts

A magic-link request must always answer 202 with the same body and the same time. The lookup
and the mail must run in the background.
