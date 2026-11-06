---
id: "000076"
title: A Tailwind border has a style
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/
scope:
  - frontend/
---

# A Tailwind border has a style

A Tailwind border width must have `border-solid` or `border-dashed`. A single-side border must
start with `border-0`, for example `border-0 border-b border-solid border-line`.

Reason: Tailwind preflight is off, so the initial border is `medium` and `none`.
