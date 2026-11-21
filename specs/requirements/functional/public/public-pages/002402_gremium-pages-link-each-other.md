---
id: "002402"
title: The two public pages of a Gremium link each other
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-21
implementation:
  - frontend/src/app/features/public-protocols
scope:
  - frontend/src/app/features/public-protocols
---

# The two public pages of a Gremium link each other

The protocols page of a Gremium must link the decisions page of the same Gremium, and the
decisions page must link the protocols page. The crumb trail must name the Gremium: "Start ›
Protokolle › <Gremium>". The page of one protocol must link the protocols page of its
Gremium.

Reason: A reader who switches between protocols and decisions stays in one Gremium.

Test: A frontend unit test finds the link to `/decisions/<slug>` on `/protocols/<slug>` and
the link back.
