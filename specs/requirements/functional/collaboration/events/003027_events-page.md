---
id: "003027"
title: Veranstaltungen is a page of its own with a list and a detail
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/events/events-page.component.ts
  - frontend/src/app/layout/nav.service.ts
  - backend/app/modules/events/router.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# Veranstaltungen is a page of its own with a list and a detail

The platform must have the page `Veranstaltungen` at `/events` with its own entry in the main
navigation, right after `Bestellungen`. It must be a list with a detail like the page
`Bestellungen` (002883, 002936): a row shows the name, the status, the dates and the place, and
opens the detail beside the list. The address `/events?id=<id>` must open the page with this
Event. The button `Veranstaltung anlegen` must show only for a member of a team.
The list must hold the Events of the teams of the person.
The form for a new Event and for a change must open in the pane (002937).

Reason: An Event must be easy to find, like a Bestellung. A list with a detail is how the
platform shows each element of its own.

Test: A frontend unit test opens `/events?id=<id>` and reads the detail. A frontend unit test
finds the entry after `Bestellungen`.
