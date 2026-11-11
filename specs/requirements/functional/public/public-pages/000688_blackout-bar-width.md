---
id: "000688"
title: A black bar has one fixed width
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - typst/
  - frontend/src/app/shared/markdown
---

# A black bar has one fixed width

Each black bar must have the same width, independent of the length of the marked text.

Reason: A bar with the length of the text tells the length of the name.

Test: A typst and a frontend test render two markers of different length and compare the
widths.
