---
id: "000308"
title: Every mail links its element
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# Every mail links its element

Every mail carries a link to the element that it is about. A mail must not create a new
magic-link token. Only the mail about an executed erasure has no link.
