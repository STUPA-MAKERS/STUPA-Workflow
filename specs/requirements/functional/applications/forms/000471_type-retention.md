---
id: "000471"
title: Antrag types can keep their own retention
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/application_types/models.py
  - backend/worker/retention.py
scope:
  - backend/app/modules/application_types/models.py
  - backend/worker/retention.py
---

# Antrag types can keep their own retention

An Antrag type can set `retention_months`. A type without a value must use
`privacy_settings.default_retention_months`.
