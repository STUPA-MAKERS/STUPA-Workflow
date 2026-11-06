---
id: "000151"
title: Task mails go only to who can act
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/notifications
  - frontend/src/app/pages/account
---

# Task mails go only to who can act

A mail about a task must go only to the persons who can act on the current state of the Antrag.
Such a person can read the Antrag and can fire a `requires_action` transition or still cast a
ballot in an open vote. A member who can only read the Antrag must get no mail.
