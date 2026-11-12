---
id: "000739"
title: In very high contrast, a box with a text to copy is a yellow fill
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/shared/very-high-contrast.styles.spec.ts:copyBoxes"
implementation:
  - frontend/src/app/shared/ui/_very-high-contrast.scss
scope:
  - frontend/src/app/
---

# In very high contrast, a box with a text to copy is a yellow fill

While "Hoher Kontrast" is on (000605), a box that holds an address, a command or a
configuration for a person to copy must be a yellow fill with black text (000621). Such
boxes are the address of a calendar subscription and the command and the configuration of
the MCP setup on the account page.

Reason: On the black page the box has no shade, so its text reads as plain white text and a
person does not see where the text to copy starts and ends.

Test: `frontend/src/app/shared/very-high-contrast.styles.spec.ts` reads the rules and fails
when one of the boxes does not take the fill.
