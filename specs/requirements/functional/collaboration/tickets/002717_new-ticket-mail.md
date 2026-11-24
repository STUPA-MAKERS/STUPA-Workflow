---
id: "002717"
title: A new ticket is mailed to the team of its Bereich
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_mails.py:test_created_goes_to_the_team_of_the_bereich_only"
implementation:
  - backend/app/modules/tickets/mails.py
  - backend/app/modules/tickets/access.py
  - frontend/src/app/pages/account/notifications.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A new ticket is mailed to the team of its Bereich

While the switch `Neue Tickets melden` of a Bereich is on, a new ticket must be mailed to each
person with the work right in the Bereich, except the sender. A person must be able to switch
this mail off in the own notification settings.

Reason: A person must not get the tickets of the teams in which the person does not work.

Test: A unit test creates a ticket in Bereich A and expects no mail to a person who works only
in Bereich B.
