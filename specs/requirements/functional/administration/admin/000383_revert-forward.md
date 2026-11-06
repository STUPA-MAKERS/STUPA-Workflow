---
id: "000383"
title: A config revert goes forward
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/config_revision
scope:
  - backend/app/modules/config_revision
---

# A config revert goes forward

A restore and a revert of a configuration must write a new version. A revert must work only if
the reverted version is still the newest, else it must answer 409 `stale_revert`.
