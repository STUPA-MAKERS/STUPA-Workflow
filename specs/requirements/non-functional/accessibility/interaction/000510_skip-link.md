---
id: "000510"
title: A skip link goes to the main content
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A skip link goes to the main content

The first focusable element of every page must be a link to the main content. The link must
show when it has the focus.

Reason: WCAG 2.4.1. A keyboard user must not tab through the whole navigation on each page.
