---
id: "003070"
title: An external calendar belongs to a team
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/calendar
  - backend/migrations
---

# An external calendar belongs to a team

An external calendar that is not global must belong to a team, not to a Gremium. Its entries
must show to the members of the team. The data migration must move each external calendar of a
Gremium to the inherent team.

Reason: The same rule as for the Termine: a team decides who sees a calendar.

Test: A backend test adds an external calendar to a team and reads its entries as a member and
as a person outside the team.
