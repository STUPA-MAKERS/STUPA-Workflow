---
id: "000870"
title: The move to a TOP records its time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
---

# The move to a TOP records its time

When a live Sitzung moves to a TOP, the server must record the time of the move on that TOP.
If the Sitzung moves back to a TOP that has a time, the first time must stay. A TOP that the
Sitzung never reaches has no time.

Reason: The protocol shows when the Sitzung started each TOP (000871), and the person who
writes the protocol must not type it.

Test: Unit test of the move to a TOP: the first move sets the time, and a second move keeps it.
