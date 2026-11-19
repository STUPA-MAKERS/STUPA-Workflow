---
id: "000205"
title: Empty states use one component
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Empty states use one component

An empty state must use `app-empty-state` with a message and at most one action, which creates
something. 001360 says where the face shows and 001363 that an empty state has no reset.
