---
id: "001143"
title: A live Sitzung computes the plan of the open TOPs again
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests: null
implementation: null
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# A live Sitzung computes the plan of the open TOPs again

While the Sitzung is live, a TOP that the Sitzung reached must show the recorded time of the
move (000870) as `HH:MM` instead of the planned start. The planned start of the TOP after the
current TOP must be the later of two times: now, and the recorded time of the current TOP plus
its duration. Each further TOP must follow from there as in 001141. The agenda must compute
this again each minute.

Reason: A Sitzung runs late or early. The plan of the open TOPs then shows the real expectation,
not the plan from the invitation.

Test: Unit test of the plan function with a current TOP: the next start is the later of now and
the time of the current TOP plus its duration.
