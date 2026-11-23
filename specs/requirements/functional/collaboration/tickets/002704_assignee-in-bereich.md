---
id: "002704"
title: Only a person with the work right in the Bereich is assignee or mentioned
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# Only a person with the work right in the Bereich is assignee or mentioned

The assignee of a ticket must have the work right in the Bereich of the ticket (002703). A
message must be able to mention only persons with that right. A different person must answer
422.

Reason: An assignee or a mentioned person without the right gets a mail about a ticket that the
person cannot open.

Test: A unit test assigns a ticket to a person without the right and expects 422
`assignee_not_allowed`.
