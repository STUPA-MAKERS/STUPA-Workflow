---
id: "000172"
title: A public protocol has no names and no non-public TOPs
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/protocol/public.py
  - frontend/src/app/features/public-protocols
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# A public protocol has no names and no non-public TOPs

A public protocol must show counts, never attendee names. It must show only public TOPs. The
URL must be `/protocols/<uuid>`.
