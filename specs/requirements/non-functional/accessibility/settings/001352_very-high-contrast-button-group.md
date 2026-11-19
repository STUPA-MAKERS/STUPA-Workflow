---
id: "001352"
title: In very high contrast, a head group is yellow with black gaps
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/vendor/ui-kit/src/styles/button-group.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, a head group is yellow with black gaps

While "Hoher Kontrast" is on, each button of a head group (001350) must have a yellow fill and
black text, so the 2 px gaps show black between the buttons. A selected button (001351) must
be black with yellow text and a 2 px yellow edge. A disabled button must be black with yellow
text and a dashed 2 px yellow edge. The focus ring of very high contrast stays on a focused
button.

This is an exception to 000615 for the head group: there the open state of a menu button is
the yellow fill and the closed state the edge.

Reason: The group reads as one yellow control. A black button in it is the one that differs,
so the open state is the black one.

Test: none yet; the screenshots in the a11y views show the group.
