---
id: "000261"
title: Only a user sets an invoice to paid
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget
scope:
  - backend/app/modules/budget
---

# Only a user sets an invoice to paid

A booking must not change the status of its invoice. The invoice must stay open until a user
sets "Als bezahlt markieren".
