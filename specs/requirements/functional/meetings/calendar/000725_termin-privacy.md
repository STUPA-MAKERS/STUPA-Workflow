---
id: "000725"
title: Termine are part of the privacy export and erasure
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - backend/app/modules/privacy
---

# Termine are part of the privacy export and erasure

The privacy export of a person must hold the Termine that the person created and the answers
of the person. The erasure of a person must delete the Termine of the person that have no
invitation, must remove the person as creator from the other Termine and must delete the
invitations and answers of the person.

Reason: A Termin and an answer are personal data of the person.

Test: A backend unit test erases a person and finds no private Termin and no answer of the
person.
