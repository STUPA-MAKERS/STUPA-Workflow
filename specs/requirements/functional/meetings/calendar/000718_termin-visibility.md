---
id: "000718"
title: Only the creator and the invited persons read a Termin
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
---

# Only the creator and the invited persons read a Termin

A Termin must be readable only by its creator and its invited persons. A Termin without an
invitation is private. A Termin with the switch `Für alle` (`For everyone`) must be readable by
each signed-in person. Only a person with the permission `calendar.publish` must be able to set
the switch. A read without the right must answer 404.

Reason: One object covers the private Termin, the Termin of a Gremium and the Termin of the whole
student body, and no Termin is visible to all by accident.

Test: A backend unit test reads a Termin as a third person and gets 404, then sets the switch
without the permission and gets 403.
