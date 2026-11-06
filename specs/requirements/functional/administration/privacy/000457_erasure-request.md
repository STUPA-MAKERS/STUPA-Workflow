---
id: "000457"
title: An applicant can request the erasure of an Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/applications/router.py
  - backend/app/modules/privacy
---

# An applicant can request the erasure of an Antrag

`POST /applications/{id}/erasure-request` must create an `open` request. Only `privacy.manage`
must execute or reject it. Each step must mail the applicant after the commit.
