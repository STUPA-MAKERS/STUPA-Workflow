---
id: "000278"
title: A magic-link request does not reveal accounts
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# A magic-link request does not reveal accounts

A magic-link request always answers 202 with the same body and the same time. The lookup and
the mail run in the background.
