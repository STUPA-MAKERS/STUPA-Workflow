---
id: "000603"
title: Text, icons and counts of a control share one centre line
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/vendor/ui-kit/src/lib/button/button.component.scss
  - frontend/vendor/ui-kit/src/lib/filter-select/filter-select.component.scss
  - frontend/src/app/layout/language-select/language-select.component.ts
  - frontend/src/app/layout/public-header/public-header.component.html
scope:
  - frontend/vendor/ui-kit/src/lib/button
  - frontend/vendor/ui-kit/src/lib/filter-select
  - frontend/src/app/layout
---

# Text, icons and counts of a control share one centre line

In a button, a chip or a header icon button, the centre of the capital letters of the text
must be on the centre line of the control. The centre of each icon and of each count plate
must be on the same line. The digits of a count plate must have their centre in the centre
of the plate. An icon in a round button must start on a whole pixel.

Reason: A count plate inside the text line made the line box higher than the text, so the
text and the icon moved about 1px up. The line box of a chip text puts the capitals off its
middle by an amount that differs between browsers, so a fixed padding is right in one
browser and wrong in another. A chip trims its text box to the capitals
(`text-box: trim-both cap alphabetic`) where the browser supports it.

Test: The style spec of the kit checks the count plate and the trimmed chip text.
Zoomed screenshot (DPR 4) of the "Kommentare" button of an application, with and without
"Felder hervorheben", and of the public top bar: the centre of the capitals, of the icons
and of the count plate are within 0.5px of the centre of the control.
