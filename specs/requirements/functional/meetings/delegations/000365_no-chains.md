---
id: "000365"
title: Delegations do not chain
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/delegations/service.py
scope:
  - backend/app/modules/delegations
---

# Delegations do not chain

In one meeting a person must be a delegator or a delegate, never both.
