---
id: "000406"
title: The phone layout does not change the desktop
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The phone layout does not change the desktop

Phone styles must be only additive `max-width` queries. Every page must have a usable phone
layout, except the beamer view.
