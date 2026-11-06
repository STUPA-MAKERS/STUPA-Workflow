---
id: "000031"
title: A poll shows only counts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/voting/poll.py
  - frontend/src/app/features/voting
---

# A poll shows only counts

A poll shows the count per option and "n Antworten". It must not show a disclaimer such as
"Meinungsbild, kein Beschluss". A poll has no quorum, no majority and no lot, and it does not
change an Antrag.
