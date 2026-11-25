---
id: "003029"
title: The detail of an Event shows its money, decisions and series
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/events/event-detail.component.html
  - backend/app/modules/events/service.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# The detail of an Event shows its money, decisions and series

The detail of an Event must show, in this order: the name with the number and the status; the
actions; the fields of 003023; the totals of 000479; the decisions of 000482; the other Events
of its series (000483); the list `Verknüpft`. The detail must not be a dialog. The totals, the
decisions and the series must use the links of the Event.

Reason: The money and the decisions are the reason why an Event is an element of its own. They
must be at one place with the dates.

Test: A frontend unit test opens an Event and reads the sections in their order.
