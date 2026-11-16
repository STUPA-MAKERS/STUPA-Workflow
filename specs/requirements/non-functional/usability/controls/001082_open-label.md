---
id: "001082"
title: A button that opens a file says Öffnen
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/core/i18n/catalog.spec.ts:catalog"
implementation:
  - frontend/src/app/core/i18n/catalog
scope:
  - frontend/src/app
---

# A button that opens a file says Öffnen

A button or link that opens a file in the viewer (001080) must say "öffnen" and not
"herunterladen", for example "PDF öffnen" and "Als PDF öffnen". It must show the icon `file`.
A button that downloads a format that the viewer cannot show keeps "herunterladen" or
"exportieren" and the icon `download`. The download button in the top bar of the viewer keeps
the icon `download`.

Reason: The label must say what the click does. A screen reader user and a sighted user expect
a download from "herunterladen".

Test: The i18n parity test, and a review of the labels of 001080.
