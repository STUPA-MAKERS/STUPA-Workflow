---
id: "000150"
title: Anyone can report a help ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# Anyone can report a help ticket

A signed-in person must always be able to send a help ticket from the help menu. A signed-out
person must be able to send one only while `tickets.publicEnabled` is on, with an e-mail
address and a solved ALTCHA. The answer must hold only the ticket number.
