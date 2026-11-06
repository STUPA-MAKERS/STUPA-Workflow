---
id: "000472"
title: The public Antrag POST is protected
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications
  - backend/app/shared/antiabuse.py
scope:
  - backend/app/modules/applications
  - backend/app/shared/antiabuse.py
---

# The public Antrag POST is protected

The create of an Antrag without login must use the ALTCHA, the rate limit and the body cap of
`shared/antiabuse.py`.
