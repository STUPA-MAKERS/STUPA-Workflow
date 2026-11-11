---
id: "000735"
title: A card can link a Termin
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/todos/links.py
  - backend/app/modules/todos/link_view.py
  - frontend/src/app/features/todos/link-picker/todo-link-picker.component.ts
  - frontend/src/app/features/calendar/appointment-detail/appointment-detail.component.html
scope:
  - backend/app/modules/todos
  - backend/app/modules/calendar
  - frontend/src/app/features/todos
---

# A card can link a Termin

The section `Verknüpft` of a card must offer the kind `Termin`. The link picker must find only the
Termine that the person can read (§F/meetings/calendar/000718). The detail of a Termin must show
the cards that link it (§F/collaboration/todos/000573).

A person who can read the card but not the Termin must read only the title, the start, the end
and the place of the linked Termin. That person must never read its description, its invited
Gremien and persons or its answers.

Reason: The work for a Termin is on cards, and the card must lead to the Termin. The key data of
a Termin are enough to plan the work, and the invitations stay with the invited persons.

Test: A backend unit test links a Termin to a card, reads the card as a board reader who is not
invited, and finds the title and the start but no description, no invitation and no answer.
