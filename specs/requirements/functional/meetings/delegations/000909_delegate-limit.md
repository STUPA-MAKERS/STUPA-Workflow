---
id: "000909"
title: A delegate holds a limited number of delegations
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/delegations
  - backend/app/modules/gremien
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# A delegate holds a limited number of delegations

A Gremium must have the setting `delegationMaxPerDelegate`. In one meeting a delegate must not
hold more delegations than this value. A further delegation must answer 409 `delegate_limit`. A
pool seat must not count.

Reason: The Organisationssatzung lets a member hold at most two Stimmrechtsübertragungen.

Test: An integration test that creates one delegation more than the limit.
