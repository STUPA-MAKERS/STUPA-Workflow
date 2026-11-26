---
id: "003030"
title: Folgeveranstaltung anlegen copies the plan
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/service.py
  - frontend/src/app/pages/events/event-detail.component.ts
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# Folgeveranstaltung anlegen copies the plan

The menu of an Event must have `Folgeveranstaltung anlegen`. It must open the form for a new
Event with the name, the description, the place, the shop, the team and the series of the
Event. The new Event must not get the dates, the status or the links.

Reason: The plan of a recurring Event repeats each time. The Anträge, Buchungen and decisions
belong to one edition only (000484).

Test: A frontend unit test opens `Folgeveranstaltung anlegen` and reads the copied fields and
empty dates.
