---
id: "000918"
title: A late meeting date shows a warning
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - frontend/src/app/features/meetings
---

# A late meeting date shows a warning

The meeting form must show a warning when the date is nearer than the invitation period of the
kind (000917). The period of a `repeat` meeting is `inviteDaysExtraordinary`. The warning must
not block the save.

Reason: A Sitzung that is invited too late can still take place when no member objects.

Test: A component test of the meeting form.
