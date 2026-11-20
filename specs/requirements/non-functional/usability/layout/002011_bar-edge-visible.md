---
id: "002011"
title: No resting surface at the edge of a bar has the colour of the bar
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/styles/tokens.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# No resting surface at the edge of a bar has the colour of the bar

A surface in the page body that scrolls to the edge of the navigation bar must not have the
bar colour (002010) at rest. A surface that scrolls to the edge of a scrolled head must not have
the colour of that head, which is the page colour. This applies to rows, cards, chips, fields
and group surfaces. The bar colour is a token of its own (`--color-bar`), so a change of the
bar colour does not change the surfaces of the body.

Reason: The bars have no shadow and no line. If a surface of the body has the same colour as
the bar, the edge of the bar does not show where that surface touches it.

Test: A probe in the screenshot run reads the background colour of every element in the body
that touches the edge of the navigation bar and finds none with the bar colour, and every element
that touches the edge of a scrolled head and finds none with the colour of the head.
