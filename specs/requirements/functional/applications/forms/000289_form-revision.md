---
id: "000289"
title: A form change is versioned and audited
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - backend/app/shared/config_schemas.py
  - backend/app/modules/config_revision
---

# A form change is versioned and audited

Every new form version writes a config revision and an audit entry.
