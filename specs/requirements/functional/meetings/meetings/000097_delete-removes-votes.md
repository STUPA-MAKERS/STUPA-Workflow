---
id: "000097"
title: A meeting delete removes its votes
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - backend/app/modules/applications
---

# A meeting delete removes its votes

The delete of a meeting deletes all its votes with their ballots and markers. An Antrag that
such a vote decided keeps its status. Its timeline shows "Abstimmung gelöscht (mit Sitzung)".
The confirmation dialog names the number of votes. The audit entry carries the vote count.
