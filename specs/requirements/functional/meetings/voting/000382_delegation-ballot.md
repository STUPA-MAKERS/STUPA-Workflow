---
id: "000382"
title: A delegation ballot is a second ballot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/voting
  - backend/app/modules/delegations
---

# A delegation ballot is a second ballot

An own ballot and a delegation ballot must be two ballots with two voters. Each delegation
ballot must write a `delegation_use` audit entry.
