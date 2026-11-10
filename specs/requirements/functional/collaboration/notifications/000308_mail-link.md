---
id: "000308"
title: Every mail links its element
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/notifications/links.py
  - backend/app/modules/notifications/layout.py
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# Every mail links its element

Every mail must carry a link to the element that it is about. A mail must not create a new
magic link or a new login link (000630). The mails that 000583 names are the exception: they
send a login link. Only the mail about an executed erasure has no link.

Reason: A token in every status mail multiplies the access tokens of an Antrag.
