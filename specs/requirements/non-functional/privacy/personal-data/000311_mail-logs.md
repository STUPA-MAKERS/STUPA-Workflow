---
id: "000311"
title: Mail logs hold no personal data
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/notifications/mail.py
  - backend/worker/mail.py
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# Mail logs hold no personal data

A mail log line must hold only the recipient domains and the idempotency key. It must never
hold an address, the subject, the body or the SMTP password.
