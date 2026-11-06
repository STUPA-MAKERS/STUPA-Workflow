---
id: "000525"
title: Each mail has a plain text part
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/notifications/mail.py
scope:
  - backend/app/modules/notifications
---

# Each mail has a plain text part

Each mail must have a `text/plain` part with the full content. An HTML part is optional.

Reason: Some screen readers and mail programs show only plain text.
