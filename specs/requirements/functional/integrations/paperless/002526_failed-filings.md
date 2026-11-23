---
id: "002526"
title: The admin page lists the filings that failed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# The admin page lists the filings that failed

The admin page `Paperless` must list each filing whose job failed for the last time, with the
element, the time and the error. Each row must have the action `Erneut versuchen`, which starts
the job again.

Reason: A filing that fails for good must not get lost without a sign.

Test: A unit test lets a job fail 8 times and expects the row in the list.
