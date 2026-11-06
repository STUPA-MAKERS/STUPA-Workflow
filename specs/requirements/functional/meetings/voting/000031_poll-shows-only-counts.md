---
id: "000031"
title: A poll shows only counts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/voting/poll.py
  - frontend/src/app/features/voting/poll-result
scope:
  - backend/app/modules/voting/poll.py
  - frontend/src/app/features/voting
---

# A poll shows only counts

A poll must show the count per option and "n Antworten". It must not show a disclaimer such as
"Meinungsbild, kein Beschluss". A poll must have no quorum, no majority and no lot, and it must
not change an Antrag.
