---
id: "000313"
title: A reporter account follows its tickets
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A reporter account follows its tickets

A reporter with an account must be able to read its own tickets under "Tickets" and to write
messages there. It must see the report, the public notes and the status changes. It must not
see the assignee, the context, internal notes or to-dos. A report without an account must stay
one-way.
