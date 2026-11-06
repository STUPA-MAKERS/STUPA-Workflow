---
id: "000287"
title: A pattern check cannot hang
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms/validation.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# A pattern check cannot hang

A `pattern` check must run on at most 4096 characters and for at most 1 second. A longer input
or a timeout must make the field invalid, never a 500.
