---
id: "003063"
title: The managers of a team add its members by hand
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - frontend/src/app/features/gremien
---

# The managers of a team add its members by hand

The members of a team that is not an inherent team must be persons that a manager of the team
adds or removes by hand. Each member must have the role `member` or `manager`. A team must keep
at least one manager, or else an admin manages it.

Reason: A work group has no OIDC group, and its members change often.

Test: A backend test adds a person as `member`, makes the person a `manager` and refuses to
remove the last manager.
