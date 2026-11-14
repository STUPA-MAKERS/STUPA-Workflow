---
id: "000911"
title: A konstituierende Sitzung takes no delegation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/delegations
  - backend/app/modules/meetings
---

# A konstituierende Sitzung takes no delegation

A delegation for a meeting of the kind `constituent` (000903) must answer 409
`delegation_no_chair`. A pool seat must stay possible.

Reason: The Organisationssatzung allows no Stimmrechtsübertragung while the Gremium has no
Vorsitz.

Test: An integration test that creates a delegation for a meeting of the kind `constituent`.
