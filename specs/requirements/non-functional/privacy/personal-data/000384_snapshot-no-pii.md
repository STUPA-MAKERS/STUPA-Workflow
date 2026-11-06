---
id: "000384"
title: A config snapshot holds no personal data
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/config_revision
---

# A config snapshot holds no personal data

A config snapshot must hold only configuration, never personal data.

Reason: The chain cannot change, so personal data in it could never be deleted.
