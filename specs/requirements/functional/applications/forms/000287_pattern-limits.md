---
id: "000287"
title: A pattern check cannot hang
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# A pattern check cannot hang

A `pattern` check runs on at most 4096 characters and for at most 1 second. A longer input or
a timeout makes the field invalid, never a 500.
