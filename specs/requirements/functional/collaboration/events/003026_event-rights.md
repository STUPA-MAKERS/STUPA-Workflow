---
id: "003026"
title: The team of an Event gives its rights
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/access.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# The team of an Event gives its rights

Each Event must belong to one team (003060), not to a board. Each member of the team must read
and write the Event: create, change, status and delete. A person who is not a member must not
read the Event, and the API must answer 404. A member of the parent team or of a sub-team must
not get access by this alone (003064). A member who writes an Event can move it to another team
that the person is a member of. The OAuth scopes of the to-dos must give the same access.

Reason: The team decides who works together, for the board as for the Event. An Event that
hangs on a team stays where it is when the board of the team changes.

Test: A backend unit test reads and changes an Event as a member of its team, and gets 404 as a
member of its parent team only.
