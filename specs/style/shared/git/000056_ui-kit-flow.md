---
id: "000056"
title: ui-kit changes go to ui-kit development first
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/vendor/ui-kit
---

# ui-kit changes go to ui-kit development first

A ui-kit pull request targets the `development` branch of `STUPA-MAKERS/ui-kit`. Merge it with
a merge commit. Then point the app submodule `frontend/vendor/ui-kit` at that merge commit.
Do not install packages in the submodule.
