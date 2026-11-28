---
id: "003132"
title: The detail of an Event shows the start and the end side by side
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/pages/events/event-detail.component.spec.ts:EventDetailComponent"
implementation:
  - frontend/src/app/pages/events/event-detail.component.html
  - frontend/src/app/pages/events/event-detail.component.ts
  - frontend/src/app/pages/events/events.util.ts
scope:
  - frontend/src/app/pages/events
---

# The detail of an Event shows the start and the end side by side

The detail of an Event must show its dates as two fields in one row of the field group, like
"Eingegangen" and "Aktualisiert" on the detail of an Antrag (`app-field-pair`): `Beginn`
(`Start`) on the left with the day of the start and its time, and `Ende` (`End`) on the right
with the day of the end and its time, for example `12.03.2027, 18:00` and `14.03.2027`. The
detail must not show the start and the end as one range in one field. An Event without a day
of the end must show `Ende` with the day of the start when it has a time of the end, and must
not show `Ende` when it has none. An Event without a day of the start must show neither field.
The two fields must stack where the row is too narrow for two. The list rows, the calendar and
the export keep their own format.

Reason: One range such as `12.03.–14.03.2027` is hard to read, and the start and the end are
two fields of the Event (003023). Two fields side by side read like the other details.

Test: A frontend unit test opens an Event from 12.03. to 14.03.2027 and reads `Beginn` and
`Ende` as two fields in one pair.
