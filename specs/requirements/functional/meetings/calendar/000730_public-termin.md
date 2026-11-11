---
id: "000730"
title: A Termin can be public
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/appointments.py
  - backend/app/modules/calendar/public.py
  - frontend/src/app/features/calendar/appointment-dialog/appointment-dialog.component.html
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# A Termin can be public

A Termin must have the switch `Öffentlich` (`Public`). Only a person with the permission
`calendar.publish` must be able to set the switch. A public Termin must also be readable by each
signed-in person, as with the switch `Für alle`.

A read without a sign-in must give only the title, the start, the end, the place and the
description of a public Termin. It must never give the creator, the invited Gremien and persons
or the answers.

Reason: Dates such as an election or a general assembly are for the whole university. The public
part of a Termin holds no personal data.

Test: A backend unit test reads a public Termin without a session and finds no creator, no
invitation and no answer in the response. A second test reads a Termin that is not public without
a session and gets 404.
