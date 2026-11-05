---
id: "000313"
title: A reporter account follows its tickets
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A reporter account follows its tickets

A reporter with an account reads its own tickets under "Tickets" and writes messages there.
It sees the report, the public notes and the status changes. It does not see the assignee,
the context, internal notes or to-dos. A report without an account stays one-way.
