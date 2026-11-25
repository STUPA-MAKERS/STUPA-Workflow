---
id: "003028"
title: The page Veranstaltungen has four segments
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/listing.py
  - frontend/src/app/pages/events/events-page.component.ts
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# The page Veranstaltungen has four segments

The page `Veranstaltungen` must have these segments in this order: `Kommend` (phase `open` and
an end, else a start, from today, or no start; the earliest first), `Vergangen` (phase `open`
and an end, else a start, before today; the newest first), `Erledigt` (phase `done`) and
`Verworfen` (phase `void`), each with the newest start first. The segments must follow the
phases (003036) and must not name a status. `Kommend` must be the default. A segment must not show a
count. The list must have the search and the chips `Team` and `Reihe`.

Reason: The segments follow the work: plan the Event, settle it after the day. A past Event that
is not settled must stay visible until a person settles it.

Test: A backend unit test puts a planned Event of yesterday into `Vergangen`, a planned Event of
tomorrow into `Kommend` and an Event of the phase `done` into `Erledigt`.
