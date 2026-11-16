---
id: "001084"
title: The file viewer is dark frosted glass
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - frontend/vendor/ui-kit/src/lib/file-viewer
scope:
  - frontend/vendor/ui-kit/src/lib/file-viewer
---

# The file viewer is dark frosted glass

The whole file viewer must be one dark frosted glass over the page behind it: a dark tint over a
strong blur, so the page shows only as a dark blur and none of its text stays readable, also at
the edges of the screen. The top bar must be at least as dark as the rest of the viewer. The
tint must keep the name and the buttons at a contrast of at least 4.5:1 on a light page. With
less transparency (000596) the viewer must be the solid tint.

Reason: The viewer is an overlay like the sheets and dialogs, which are glass. A solid black
surface looks like a different app, and a bar lighter than the rest draws the eye away from the
file.

Test: A screenshot of the viewer on a light and on a dark page, on a phone and on a desktop, and
with less transparency.
