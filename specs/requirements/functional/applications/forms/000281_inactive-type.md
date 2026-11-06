---
id: "000281"
title: A type without an active form is closed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/application_types/service.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
  - backend/app/modules/application_types
---

# A type without an active form is closed

An Antrag type without an active form version must accept no new Antrag and must not be in the
public list.
