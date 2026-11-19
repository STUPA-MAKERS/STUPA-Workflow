---
id: "001702"
title: A bulk message adds one public comment to each Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/applications/router.py
  - frontend/src/app/pages/applications/bulk-dialog/bulk-dialog.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A bulk message adds one public comment to each Antrag

`Mitteilung senden` (`Send message`) must add the same public comment to each selected Antrag.
Each comment must send the normal comment mail to its applicant.

Reason: Each applicant must find the message at the own Antrag, as with a single comment.

Test: A backend integration test sends a message to three Anträge and checks three comments and three mails.
