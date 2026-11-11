---
id: "000688"
title: A black bar has one fixed width and the text colour
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - typst/template/protocol.typ
  - frontend/src/app/shared/markdown/markdown-view.component.scss
scope:
  - typst/
  - frontend/src/app/shared/markdown
---

# A black bar has one fixed width and the text colour

Each black bar must have the same width, independent of the length of the marked text. On a page the bar must have
the text colour, so it is light in the dark and the very high contrast view. In the PDF the
bar must be black.

Reason: A bar with the length of the text tells the length of the name.

Test: A typst and a frontend test render two markers of different length and compare the
widths.
