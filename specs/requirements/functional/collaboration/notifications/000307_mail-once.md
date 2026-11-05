---
id: "000307"
title: A mail is sent once
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/notifications
  - backend/app/worker/mail.py
---

# A mail is sent once

Every mail has a stable idempotency key, so a retry does not send it twice.
