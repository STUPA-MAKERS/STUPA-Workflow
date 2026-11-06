---
id: "000056"
title: ui-kit changes go to ui-kit development first
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - frontend/vendor/ui-kit
---

# ui-kit changes go to ui-kit development first

A ui-kit pull request must target the `development` branch of `STUPA-MAKERS/ui-kit` and must
merge with a merge commit. Then the app submodule `frontend/vendor/ui-kit` must point at that
merge commit. Nobody must install packages in the submodule.
