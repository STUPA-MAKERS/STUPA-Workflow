---
id: "000176"
title: Integrations are optional
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/
  - frontend/src/app/
scope:
  - backend/app/
  - frontend/src/app/
---

# Integrations are optional

Every integration with an external system, for example Nextcloud or a wiki, must be optional.
It must be off without settings and must have a switch per feature. An outage of the external
system must not make a page of the platform fail: the page must show without the data of the
integration.
