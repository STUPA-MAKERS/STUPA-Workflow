---
id: "002703"
title: The work right in a Bereich comes from the Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
