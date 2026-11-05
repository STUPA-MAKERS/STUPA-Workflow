---
id: "000311"
title: Mail logs hold no personal data
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/notifications
  - backend/app/worker/mail.py
---

# Mail logs hold no personal data

A mail log line holds only the recipient domains and the idempotency key. It never holds an
address, the subject, the body or the SMTP password.
