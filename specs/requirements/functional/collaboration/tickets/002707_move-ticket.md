---
id: "002707"
title: A ticket can move to a different Bereich
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A ticket can move to a different Bereich

A person with the work right in the Bereich of a ticket must be able to move the ticket to each
other Bereich. The move must clear the Kategorie. The move must clear the assignee when the
assignee has no work right in the new Bereich. The move must write an event with both Bereiche.

Reason: A mail often reaches the wrong team. The person who sees that must be able to pass the
ticket on, also to a Bereich that the person cannot read.

Test: A unit test moves an assigned ticket to a Bereich where the assignee has no right and
expects no assignee and one event.
