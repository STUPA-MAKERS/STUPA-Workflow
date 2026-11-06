---
id: "000283"
title: Section fields make wizard steps
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
  - frontend/src/app/pages/applications
---

# Section fields make wizard steps

A field of type `section` must start a new wizard step and must hold no answer. A form without
a section has one step.
