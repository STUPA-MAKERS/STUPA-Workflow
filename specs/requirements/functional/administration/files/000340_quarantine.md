---
id: "000340"
title: An unscanned file is not served
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/files/service.py
  - backend/app/modules/files/router.py
scope:
  - backend/app/modules/files
  - backend/app/modules/media
---

# An unscanned file is not served

A download of an unscanned file must answer 409. A download of an infected or removed file must
answer 410.
