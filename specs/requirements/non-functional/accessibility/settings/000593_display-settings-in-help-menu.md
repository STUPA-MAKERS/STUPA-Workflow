---
id: "000593"
title: The help menu holds the display settings
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/help/help-menu/help-menu.component.spec.ts:HelpMenuComponent"
implementation:
  - frontend/src/app/features/help/help-menu
scope:
  - frontend/src/app/features/help
  - frontend/vendor/ui-kit
---

# The help menu holds the display settings

The help menu must show a group "Darstellung" between "Barrierefreiheit" and "Problem
melden". The group must have one switch for each of these settings: "Dunkles Design"
(000218), "Mehr Kontrast" (000595), "Weniger Bewegung" (000219), "Weniger Transparenz"
(000596), "Eingabefelder hervorheben" (000598) and, last, "Sehr hoher Kontrast" (000605). The group must show with and without a login, in the popover, in the phone sheet
of the public header and in the "Mehr" sheet.

The public header must show its controls in this order: the language select, the help
button, the theme switch, then "Anmelden" or "Abmelden".

Reason: A person who needs one of these settings must find it in one place on every page,
also without an account and without a change in the system settings.

Test: `frontend/src/app/features/help/help-menu/help-menu.component.spec.ts`.
