---
id: "003023"
title: An Event holds these fields
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/models.py
  - backend/app/modules/events/schemas.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# An Event holds these fields

An Event must hold these fields:

| Field | Content | Required |
| --- | --- | --- |
| `title` | The name of the Event, at most 300 characters | yes |
| `status` | The status (003025) | yes |
| `descriptionMd` | A description in Markdown, at most 20000 characters | no |
| `startsOn`, `startTime` | The day of the start and an optional time | no |
| `endsOn`, `endTime` | The day of the end and an optional time | no |
| `place` | The place, at most 300 characters | no |
| `participants` | The expected number of participants, a whole number from 0 | no |
| `seriesId` | The series (`Reihe`) of the Event (000483) | no |
| `shopUrl` | The link to the shop of the Event (003024) | no |
| `teamId` | The team of the Event (003026, 003060) | yes |

The rules of 000736 for the times must stay: the end must not be before the start, a time needs
its day, and an Event without a time is an all-day entry. A change must send `version`, and a
stale `version` must get 409 `event_version_conflict`.

Reason: These are the fields that the event data of a card holds today, plus the shop, the status and
the team. One fixed set keeps the form, the API and the calendar the same.

Test: A backend unit test of the schema accepts an Event with only a title, and refuses an end
before the start and a title of 301 characters.
