---
id: "000621"
title: In very high contrast, everything on a yellow fill is black
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/e2e/06-axe.spec.ts:textOnYellowIsBlack"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, everything on a yellow fill is black

While "Sehr hoher Kontrast" is on, every text, icon and edge that is on a yellow fill must be
black. This includes a status box, a count, a key hint such as "Strg+K" and an icon in a chosen
row or a chosen tile. A destructive label stays dark red (000598).

Reason: White on yellow has a contrast of 1.07:1, so a person cannot read it. The white edges and
white state texts of 000605 are for the black background.

Test: `frontend/e2e/06-axe.spec.ts` measures each text on a yellow fill and fails
below a contrast of 7:1.
