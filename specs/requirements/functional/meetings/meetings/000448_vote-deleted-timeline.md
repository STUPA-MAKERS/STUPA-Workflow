---
id: "000448"
title: The timeline shows a vote deleted with its meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/service/lifecycle.py
  - backend/app/modules/applications/service/reads.py
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/applications
---

# The timeline shows a vote deleted with its meeting

When a meeting delete removes a vote, the timeline of the decided Antrag must show "Abstimmung
gelöscht (mit Sitzung)".
