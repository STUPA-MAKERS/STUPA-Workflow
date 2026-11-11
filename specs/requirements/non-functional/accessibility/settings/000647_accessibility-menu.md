---
id: "000647"
title: Accessibility has its own menu
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/features/help/a11y-menu/a11y-menu.component.spec.ts:A11yMenuComponent"
implementation:
  - frontend/src/app/features/help/a11y-menu
  - frontend/src/app/layout/shell.component.ts
  - frontend/src/app/layout/public-header/public-header.component.html
scope:
  - frontend/src/app/features/help
  - frontend/src/app/layout
  - frontend/vendor/ui-kit
---

# Accessibility has its own menu

The app must have a menu "Barrierefreiheit" that is separate from the help menu. Its button must
show the icon `eye` and the label "Barrierefreiheit". The button must sit directly above "Hilfe"
in the navigation rail and directly before the help button in the public header. On a phone, the
public header button must open the menu as a bottom sheet, and the "Mehr" sheet must show the
menu as its own group "Barrierefreiheit" directly before the group "Hilfe".

The menu must show, in this order: the group "Darstellung" (000593), a separator and the link
"Erklärung zur Barrierefreiheit" to `/accessibility` (000496). The help menu must show only
"Handbuch im Wiki" and "Problem melden" (000150).

Reason: A person who needs an accessibility setting looks for it under accessibility, not under
help. One button with the accessibility icon finds the settings and the statement in one place.

Test: `frontend/src/app/features/help/a11y-menu/a11y-menu.component.spec.ts`.
