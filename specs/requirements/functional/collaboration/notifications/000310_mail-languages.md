---
id: "000310"
title: Mail texts are in German and English
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
---

# Mail texts are in German and English

Every built-in mail must exist in German and in English. An admin override must replace the
built-in text. A subject must not have a line break.
