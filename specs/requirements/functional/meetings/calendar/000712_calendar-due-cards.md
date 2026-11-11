---
id: "000712"
title: The Kalender shows every readable card with a due date
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The Kalender shows every readable card with a due date

The Kalender must show the due cards of every board that the person reads, not only the cards
assigned to the person. The filter `Nur meine` (`Only mine`) must limit the cards to the assigned
cards and the Termine to those that the person created or is invited to.

Reason: A Gremium plans with the deadlines of the whole board. The filter keeps the view small
for one person.

Test: A backend unit test reads a due card of another assignee and does not find it with the
filter.
