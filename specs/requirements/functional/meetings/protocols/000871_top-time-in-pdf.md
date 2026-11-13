---
id: "000871"
title: The protocol PDF shows the time above each TOP
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - backend/app/modules/protocol
  - typst/
---

# The protocol PDF shows the time above each TOP

The protocol PDF must show the time of a TOP (000870) as `HH:MM Uhr` in the time zone
Europe/Berlin. The time must be grey, small and centered on its own line above the heading of
the TOP. A TOP without a time must have no line.

Reason: A reader sees the course of the Sitzung, and the time does not compete with the
heading.

Test: Integration test of the typst service: the time line comes before the TOP heading, and a
TOP without a time has none.
