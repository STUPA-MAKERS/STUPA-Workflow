---
id: "001141"
title: The agenda shows a time plan from the durations
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
implementation:
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# The agenda shows a time plan from the durations

When the Sitzung has a start time, the agenda must show the planned start of each TOP as
`ca. HH:MM` in the row subline, followed by the duration as `N Min.`. The planned start of the
first TOP must be the start time of the Sitzung. The planned start of each further TOP must be
the planned start of the TOP before it plus the duration of that TOP. A TOP without a duration
must count as 0 minutes and must show no duration. The plan must follow the order of the agenda,
so a move of a TOP must change the plan at once.

Reason: The agenda becomes a time plan without arithmetic by hand (T-0019).

Test: Unit test of the plan function: the starts add up in agenda order, and a TOP without a
duration adds 0. Component test of the agenda pane: the subline shows `ca. HH:MM · N Min.`.
