---
id: "000719"
title: An invited person answers a Termin
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/appointments.py
  - frontend/src/app/features/calendar/appointment-detail/appointment-detail.component.ts
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# An invited person answers a Termin

Each invited person must be able to answer a Termin with `Zusage`, `Absage` or `Vorbehalt`
(`Accept`, `Decline`, `Tentative`) and to change the answer until the Termin ends. The creator and
the invited persons must see the answers as a list of names. A change of the start or the end
must clear the answers.

Reason: The person who invites must know who comes. An answer to an old time says nothing
about the new time.

Test: A backend unit test answers a Termin, moves its start and reads no answer.
