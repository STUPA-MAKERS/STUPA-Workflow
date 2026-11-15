---
id: "000026"
title: A tie rejects a motion
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/voting/tally.py
  - backend/app/modules/voting/service/create.py
  - backend/app/modules/documents/service.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/documents
  - frontend/src/app/features/voting
---

# A tie rejects a motion

A tie in a motion must give the result `rejected`. A motion has no result
"Stimmengleichheit", also not in the Antrag PDF (000881). Only an election can end in a tie,
which the lot decides (000027).
