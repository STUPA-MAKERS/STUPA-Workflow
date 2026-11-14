---
id: "000903"
title: A meeting has a kind
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# A meeting has a kind

A meeting must have one of the kinds `ordinary` ("Ordentliche Sitzung"), `extraordinary`
("Außerordentliche Sitzung"), `repeat` ("Wiederholungssitzung") or `constituent`
("Konstituierende Sitzung"). A new meeting must start as `ordinary`. The kind must change only
while the meeting is `planned`.

Reason: The quorum, the invitation period and the count of absences depend on the kind of the
meeting.

Test: An integration test that changes the kind of a live meeting and gets 409.
