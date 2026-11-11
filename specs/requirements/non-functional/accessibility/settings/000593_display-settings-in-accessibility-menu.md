---
id: "000593"
title: The accessibility menu holds the display settings
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/features/help/help-menu/help-menu.component.spec.ts:HelpMenuComponent"
implementation:
  - frontend/src/app/features/help/help-menu
scope:
  - frontend/src/app/features/help
  - frontend/vendor/ui-kit
---

# The accessibility menu holds the display settings

The accessibility menu (000647) must show a group "Darstellung" before the link
"Erklärung zur Barrierefreiheit". The group must have one switch for each of these settings, in this order: "Dunkles Design"
(000218), "Weniger Bewegung" (000219), "Weniger Transparenz" (000596), "Mehr Kontrast"
(000595) and, last, "Hoher Kontrast" (000605), so that the two contrast settings sit together. The highlighted fields of 000598 have no
switch of their own: they are part of "Hoher Kontrast". The group must show with and without a login, in the popover, in the phone sheet
of the public header and in the group "Barrierefreiheit" of the "Mehr" sheet. A sheet or a popover that holds the group must
stay open when the person changes a switch or resets the settings, so that the person can set
the next one. The "Mehr" sheet must show the switch "Dunkles Design" only in this group: the
account part of the sheet has no second one, because one setting has one switch on a screen.

The public header must show its controls in this order: the language select, the
accessibility button, the help button, then "Anmelden" or "Abmelden". The public header must not
have a theme button of its own, because "Dunkles Design" is in the accessibility menu and the
header has no room for a fourth button on a phone.

Reason: A person who needs one of these settings must find it in one place on every page,
also without an account and without a change in the system settings.

Test: `frontend/src/app/features/help/help-menu/help-menu.component.spec.ts`.
