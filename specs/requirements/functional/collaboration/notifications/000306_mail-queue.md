---
id: "000306"
title: Mails go through the queue
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# Mails go through the queue

The API only puts a mail in the queue. The worker sends it. A mail failure must not fail the
request. Without a queue, the mail is logged and dropped.
