---
id: "002703"
title: The work right in a Bereich comes from the Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_a_ticket_of_another_bereich_is_404"
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_ticket_work_gives_the_bereiche_of_the_gremium"
  - "backend/tests/integration/modules/tickets/test_ticket_areas_api.py:test_a_gremium_role_works_only_in_the_bereiche_of_its_gremium"
implementation:
  - backend/app/modules/tickets/access.py
  - backend/app/modules/tickets/router.py
  - backend/app/modules/tickets/service/reads.py
  - backend/app/modules/tickets/service/base.py
  - backend/app/modules/gremien/gremium_roles.py
  - frontend/src/app/core/auth/auth.service.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The work right in a Bereich comes from the Gremium

A person must be able to work on the tickets of a Bereich only with the Gremium permission
`ticket.work` in the Gremium of the Bereich, or with the global permission `ticket.manage`. To
work on a ticket means to read it, to set status, assignee and Kategorie, and to write internal
or public messages. For each other person the ticket must answer 404, except for the person who
sent it (000313).

Reason: Gremium rights come only from the membership (000267), so a Gremium gets its helpdesk
team from its roles, without a second list of members. The global permission keeps the platform
team, which is not a Gremium.

Test: A unit test reads a ticket of Gremium A with `ticket.work` only in Gremium B and expects
404.
