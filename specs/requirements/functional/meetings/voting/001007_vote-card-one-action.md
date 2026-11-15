---
id: "001007"
title: The vote card has one main action and a menu
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "frontend/src/app/features/meetings/vote-card/vote-card.component.spec.ts:VoteCardComponent"
implementation:
  - frontend/src/app/features/meetings/vote-card/vote-card.component.ts
  - frontend/src/app/features/meetings/vote-card/vote-card.component.html
scope:
  - frontend/src/app/features/meetings
---

# The vote card has one main action and a menu

The vote card of a meeting must show at most one button below the counts: the next step of
the vote.

1. The next step is, in this order: "Los ziehen" for a pending lot, "Zweiter Wahlgang" or
   "Dritter Wahlgang" (000971), "Abstimmung schließen" for an open vote, "Abstimmung öffnen"
   for a prepared vote in a live meeting, "Ins Protokoll übernehmen" for a closed vote.
2. Every other action must be in the menu (⋮) beside the question: "Ins Protokoll
   übernehmen" when it is not the next step, "Erneut abstimmen" or "Wahlgang wiederholen",
   "Bearbeiten", "Abstimmung abbrechen" and "Beschlussfrage löschen". The last two are danger
   items in their own section.
3. The menu must show only the actions that the person may do now. Without such an action the
   card must show no menu.
4. The voting buttons of an open vote are not actions of the card and stay as they are.

Reason: A column of three or four equal buttons gives no next step. The lead runs the room
from the card and needs one obvious button.
