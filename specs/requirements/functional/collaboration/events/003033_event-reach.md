---
id: "003033"
title: An Event is a link kind, a search source and a calendar entry
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/todos/links.py
  - backend/app/modules/search/service.py
  - backend/app/modules/calendar/entries.py
  - backend/app/modules/graph/builtin_reads.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# An Event is a link kind, a search source and a calendar entry

An Event must be the link kind `event`, so that each element can link it (001400). The search
must have the source `Veranstaltungen` with the archived and the settled Events (000485). The
calendar must show an Event with a start like a Termin (000737, 000486), and a press must open
the Event. The graph must show an Event as a node. The picker `Veranstaltung` of a Buchung
(000480) must list the Events that the person can write, and create or delete the link of the
Event to the Buchung.

Reason: The places that show an Event today must show the new element, so that no function of an
Event is lost.

Test: A backend unit test links an Event to a Buchung, finds it in the search and reads it from
the calendar feed.
