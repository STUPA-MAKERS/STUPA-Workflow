---
id: "000280"
title: A form version is never changed
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
---

# A form version is never changed

A save creates a new form version. An Antrag keeps the form version that it started with and
always renders with it. At most one version per Antrag type is active.
