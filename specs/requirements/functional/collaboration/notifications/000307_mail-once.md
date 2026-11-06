---
id: "000307"
title: A mail is sent once
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/notifications
  - backend/worker/mail.py
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# A mail is sent once

Every mail must have a stable idempotency key, so a retry does not send it twice.
