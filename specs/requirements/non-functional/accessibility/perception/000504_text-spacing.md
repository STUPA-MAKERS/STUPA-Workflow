---
id: "000504"
title: User text spacing does not cut text
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# User text spacing does not cut text

When a user sets line height 1.5, paragraph spacing 2, letter spacing 0.12 and word spacing
0.16 times the font size, no text must be cut or hidden.

Reason: WCAG 1.4.12.
