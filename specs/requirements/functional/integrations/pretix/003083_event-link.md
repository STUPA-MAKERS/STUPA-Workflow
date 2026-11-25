---
id: "003083"
title: An Event links one pretix event
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# An Event links one pretix event

The form of an Event must have the field `Pretix-Veranstaltung`: a picker that lists the events
of the organizer of the connection by name and date. An Event must link at most one pretix
event, and a pretix event must belong to at most one Event, else the API must answer 409
`pretix_event_taken`. A person must set or remove the link only when the person writes the
Event (003026) and holds `pretix.use` (003091). When the Event has no shop (003024), the link
must set the shop to the public address of the pretix event.

Reason: The platform reads the sales of the shop that belongs to the Event. A person chooses the
shop, because the names in pretix and in the platform often differ.

Test: A backend unit test links a pretix event, reads the shop address, and gets 409 for a
second Event with the same pretix event.
