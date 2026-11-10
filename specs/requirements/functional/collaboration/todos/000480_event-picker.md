---
id: "000480"
title: A Buchung can name its Event
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/src/app/features/todos/event-link.state.ts
  - frontend/src/app/pages/expenses/expense-dialogs.state.ts
  - frontend/src/app/pages/expenses/booking-form/booking-form.component.html
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/expenses
---

# A Buchung can name its Event

The form of a Buchung must have a `Veranstaltung` picker. The picker must create or delete the
link of the Event card to the Buchung. The picker must list only Events on boards that the
person can write. An Antrag is linked from the Event card.

Reason: The person who captures a Buchung knows the Event. The link must not
need a second step on the board.

Test: A frontend unit test checks that the picker creates the card link.
