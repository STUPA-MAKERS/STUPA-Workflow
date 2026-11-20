---
id: "001356"
title: The buttons of the public header are one button group
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/layout/public-header/public-header.component.spec.ts:PublicHeaderComponent"
implementation:
  - frontend/src/app/layout/public-header/public-header.component.html
  - frontend/src/app/features/help/help-menu/help-menu.component.html
  - frontend/src/app/features/help/help-menu/help-menu.component.ts
  - frontend/src/app/features/help/help-menu/help-menu.component.scss
scope:
  - frontend/src/app/layout/public-header/
  - frontend/src/app/features/help/help-menu/
---

# The buttons of the public header are one button group

The menu buttons "Barrierefreiheit" and "Hilfe" and the button "Anmelden" (or "Abmelden") of the
public header must stand in one button group with the look of 001350 and 001351. Each menu
button is a segment of that group. An open menu is a selected segment: the accent fill, and
all four corners round. On a phone each menu button shows only its icon and is as wide as an
icon button of a group. The language switch stays a control of its own in front of the group.

Reason: Buttons that stand next to each other are one group (001354). The menu buttons of the
public header are buttons of the header, so they take the same shape as "Anmelden".

Test: `public-header.component.spec.ts` checks that both menus and the sign-in link render in
one `app-button-group` and that each menu host is a segment of it.
