---
id: "000076"
title: A Tailwind border has a style
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/
---

# A Tailwind border has a style

Add `border-solid` or `border-dashed` to a border width. Put `border-0` before a single-side
border, for example `border-0 border-b border-solid border-line`.

Reason: Tailwind preflight is off, so the initial border is `medium` and `none`.
