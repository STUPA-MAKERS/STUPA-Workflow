---
id: "000397"
title: Gremium rights come from the Gremium API
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/core/auth/auth.service.ts
scope:
  - frontend/src/app/
---

# Gremium rights come from the Gremium API

A gremium right must be checked with `auth.canInGremium` or `auth.canInAnyGremium`, or with the
server flags of the object. `auth.can` never sees a gremium right.
