---
id: "001145"
title: The time plan stays internal
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests: []
implementation: []
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# The time plan stays internal

The duration and the time plan must show only on the meeting page of a person who may read the
Sitzung. The public calendar, the public Sitzung page, the guest view, the beamer, the ICS feed
and the protocol PDF must not show them.

Reason: The plan is an estimate for the people who run the Sitzung. A public time would read as
a promise. The protocol shows the real times (000871).

Test: Unit test of the public calendar and the protocol snapshot: neither carries a duration.
