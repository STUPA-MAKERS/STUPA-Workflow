---
id: "001084"
title: The top bar of the file viewer is glass
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - frontend/vendor/ui-kit/src/lib/file-viewer
scope:
  - frontend/vendor/ui-kit/src/lib/file-viewer
---

# The top bar of the file viewer is glass

The top bar of the file viewer must be frosted glass: a dark tint over a blur of the page
behind the viewer. The tint must keep the name and the buttons at a contrast of at least 4.5:1
on a light page. With less transparency (000596) the bar must be the solid tint.

Reason: The bar is the head of an overlay, like the heads of the sheets and dialogs, which are
glass. A solid black bar looks like a different app.

Test: A screenshot of the viewer on a light and on a dark page, and with less transparency.
