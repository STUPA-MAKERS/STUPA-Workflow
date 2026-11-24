---
id: "002903"
title: The delegation dialogs use the pick rows
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.scss
  - frontend/src/app/shared/ui/_pick-rows.scss
scope:
  - frontend/src/app/features/meetings
---

# The delegation dialogs use the pick rows

The person rows of "Vertretung einrichten" and "Vertretung eintragen" must use the rows of the
pick dialogs ("TOP hinzufügen"): tiles on surface 3, no radio circle, and a check mark after the
text of the chosen row. Each row must keep the avatar before the name. A group of the list must
start with its caption inside the scroll box.

Reason: The dialogs looked different from every other pick dialog of the app and the kit.

Test: Screenshot review in light, dark and very high contrast.
