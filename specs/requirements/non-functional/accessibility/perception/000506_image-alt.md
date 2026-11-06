---
id: "000506"
title: A Markdown image has an alternative text
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - typst/template
---

# A Markdown image has an alternative text

The Markdown editor must ask for an alternative text when a user adds an image. A user can
mark the image as decorative, then the alternative text is empty. The protocol PDF must use
the same text.

Reason: WCAG 1.1.1. A screen reader reads the alternative text instead of the image.
