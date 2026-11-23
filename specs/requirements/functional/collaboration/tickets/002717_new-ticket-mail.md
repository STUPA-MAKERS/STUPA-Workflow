---
id: "002717"
title: A new ticket is mailed to the team of its Bereich
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
