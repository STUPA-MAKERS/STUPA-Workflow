---
id: "000727"
title: The Kalender search jumps to the hit
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The Kalender search jumps to the hit

The search of the Kalender must ask the server and must find entries of every month, under the
read rules of the Kalender. The desktop must show the hits as a list below the search field, each
with the icon of its kind, the title, the date and the source. A press or the Enter key on a hit
must show the month of the hit and must pick its day. The search must not remove entries from
the month grid. The phone must show the hits in place of the list of days.

Reason: A person searches for a date whose month the person does not know. A filter of the
shown month cannot find it.

Test: A frontend unit test picks a hit of another month and checks the shown month and the
picked day. A backend unit test does not find a Termin that the person does not read.
