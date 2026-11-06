---
id: "000289"
title: A form change is versioned and audited
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms/service.py
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
  - backend/app/modules/config_revision
---

# A form change is versioned and audited

Every new form version must write a config revision and an audit entry.
