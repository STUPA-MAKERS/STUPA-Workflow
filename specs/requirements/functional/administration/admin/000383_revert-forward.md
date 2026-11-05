---
id: "000383"
title: A config revert goes forward
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/config_revision
---

# A config revert goes forward

A restore and a revert of a configuration write a new version. A revert works only if the
reverted version is still the newest, else 409 `stale_revert`.
