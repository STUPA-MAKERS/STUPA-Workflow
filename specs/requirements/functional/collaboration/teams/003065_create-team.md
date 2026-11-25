---
id: "003065"
title: team.create creates a team and a team manager creates a sub-team
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/app/modules/auth
---

# team.create creates a team and a team manager creates a sub-team

A person with the global permission `team.create` or an admin must be able to create a team
without a parent. A manager of a team must be able to create a sub-team of it. The creator must
become the first manager of the new team.

Reason: Admins must not be the bottleneck for every work group, and a Gremium organises its own
Referate.

Test: A backend test creates a team with `team.create`, refuses it without the permission, and
creates a sub-team as manager of the parent.
