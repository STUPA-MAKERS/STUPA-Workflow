---
id: "000280"
title: A form version is never changed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms/service.py
  - backend/app/modules/applications/service/create.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# A form version is never changed

A save must create a new form version and must never change an old one. An Antrag must keep the
form version that it started with and must always render with it. At most one version per
Antrag type must be active.
