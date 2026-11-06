---
id: "000309"
title: A person controls their mail kinds
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
  - frontend/src/app/pages/account
---

# A person controls their mail kinds

Each person must be able to switch each mail kind on or off. The magic-link mail must not be
switchable. A mail to an address without an account must never be filtered.
