---
id: "000150"
title: Anyone can report a help ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# Anyone can report a help ticket

A signed-in person can always send a help ticket from the help menu. A signed-out person can
send one only while `tickets.publicEnabled` is on, gives an e-mail address and solves an
ALTCHA. The answer holds only the ticket number.
