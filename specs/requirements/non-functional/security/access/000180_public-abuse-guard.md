---
id: "000180"
title: Public input is protected against abuse
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/antiabuse
  - backend/app/shared/antiabuse.py
---

# Public input is protected against abuse

A public POST route must use the dependencies of `shared/antiabuse.py`: body limit (413), rate
limit (429 with `Retry-After`) and ALTCHA (400 `altcha_failed`). A signed-in person must skip
the ALTCHA.
