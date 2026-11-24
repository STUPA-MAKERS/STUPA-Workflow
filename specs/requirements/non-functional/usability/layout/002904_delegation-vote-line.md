---
id: "002904"
title: The delegation dialog says that the vote moves
kind: non-functional
status: removed
owner: frederikbeimgraben
updated: 2026-11-24
scope:
  - frontend/src/app/features/meetings
---

# The delegation dialog says that the vote moves

Below the list, "Vertretung einrichten" must show one muted line with one sentence: "Die
Vertretung stimmt für dich ab." "Vertretung eintragen" must show the same fact for the missing
member.

Reason: Without the switch the member must still know that the own vote moves (002900).

Test: A component test that finds the line.
