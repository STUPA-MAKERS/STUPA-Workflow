---
id: "000382"
title: A delegation ballot is a second ballot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/voting
  - backend/app/modules/delegations
---

# A delegation ballot is a second ballot

An own ballot and a delegation ballot are two ballots with two voters. Each delegation ballot
writes a `delegation_use` audit entry.
