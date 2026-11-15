---
id: "001006"
title: The vote card states the result once
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "frontend/src/app/features/meetings/vote-card/vote-card.component.spec.ts:VoteCardComponent"
  - "frontend/src/app/features/voting/election-result/election-result.component.spec.ts:ElectionResultComponent"
implementation:
  - frontend/src/app/features/meetings/vote-card/vote-card.component.html
  - frontend/src/app/features/voting/election-result/election-result.component.html
scope:
  - frontend/src/app/features/meetings
  - frontend/src/app/features/voting
---

# The vote card states the result once

The vote card of a meeting has this order: the question, one status line, one muted rule line,
the counts.

1. The status line of a closed vote must show only its result, for example "Angenommen",
   "Gewählt" or "Los steht aus". It must not show "Abstimmung geschlossen".
2. The status line of a prepared or a cancelled vote must show its state. An open vote has no
   status line.
3. The rule line must hold the kind, the Wahlgang, the seats, the majority rule and the end
   time in one line, for example "Wahl · 1 Posten · Einfache Mehrheit · beendet 20:20".
4. The card must not repeat the result as a heading above the counts.
5. A pending lot must show only the tag "Gleichstand" on the tied rows and the button
   "Los ziehen". It must not show a banner text about the tie.

The vote page and the beamer keep their own result heading.

Reason: The card is narrow and stands beside the protocol. A tie that the card states five
times hides the counts and the next step.
