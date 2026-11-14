---
id: "000382"
title: A delegation ballot is a ballot of its own
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation:
  - backend/app/modules/voting/service.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/delegations
---

# A delegation ballot is a ballot of its own

An own ballot and each delegation ballot must be separate ballots with separate voters. Each
delegation ballot must write a `delegation_use` audit entry.
