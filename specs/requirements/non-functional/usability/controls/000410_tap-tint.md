---
id: "000410"
title: A tap tints the whole tile
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/styles/base.scss
  - frontend/vendor/ui-kit/src/styles/_press.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A tap tints the whole tile

The default tap highlight must be off. A clickable row, card or table row must tint the whole
tile on press.
