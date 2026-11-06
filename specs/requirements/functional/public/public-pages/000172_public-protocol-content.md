---
id: "000172"
title: A public protocol has no names and no internal TOPs
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# A public protocol has no names and no internal TOPs

A public protocol must show counts, never attendee names. It must show only public TOPs. The
URL must be `/protokolle/<uuid>`.
