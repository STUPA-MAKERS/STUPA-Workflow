---
id: "000180"
title: Public input is protected against abuse
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/antiabuse
---

# Public input is protected against abuse

A public write route must check an ALTCHA solution, a rate limit and a body size limit.
