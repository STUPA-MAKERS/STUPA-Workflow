---
id: "000397"
title: Gremium rights come from the Gremium API
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
---

# Gremium rights come from the Gremium API

Check a gremium right with `auth.canInGremium` or `auth.canInAnyGremium`, or with the server
flags of the object. `auth.can` never sees a gremium right.
