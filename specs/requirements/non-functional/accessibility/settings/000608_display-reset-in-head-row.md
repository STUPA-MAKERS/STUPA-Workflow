---
id: "000608"
title: The display reset lines up with the heading and the switches
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/help/help-menu/help-menu.styles.spec.ts:HelpMenuStyles"
implementation:
  - frontend/src/app/features/help/help-menu
scope:
  - frontend/src/app/features/help
---

# The display reset lines up with the heading and the switches

The circle-arrow button "Systemeinstellungen verwenden" (000594) must have the same vertical
centre line as the text of the heading "Darstellung". Its end edge must line up with the end
edge of the switch tracks of the group, in the popover and in both sheets. This applies in
every display setting.

Reason: In "Hoher Kontrast" the button shows yellow (000614). A button that is offset
from the heading and sticks out past the switches looks misplaced.

Test: `frontend/src/app/features/help/help-menu/help-menu.styles.spec.ts`.
