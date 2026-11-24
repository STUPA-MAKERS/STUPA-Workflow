---
id: "002904"
title: The delegation dialog says that the vote moves
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.html
  - frontend/src/app/features/meetings/lead-substitute-dialog/lead-substitute-dialog.component.html
scope:
  - frontend/src/app/features/meetings
---

# The delegation dialog says that the vote moves

Below the list, "Vertretung einrichten" must show one muted line with one sentence: "Die
Vertretung stimmt für dich ab." "Vertretung eintragen" must show the same fact for the missing
member.

Reason: Without the switch the member must still know that the own vote moves (002900).

Test: A component test that finds the line.
