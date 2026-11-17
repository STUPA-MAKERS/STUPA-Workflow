---
id: "001275"
title: New events since the last visit are marked
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
implementation:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# New events since the last visit are marked

The platform must store per person the time of the last visit of the page. An event after this
time must carry a mark "neu". The navigation entry must show a dot without a number while such an
event exists. Opening the page must set the time to now, after the page has loaded the first
page of events.

Reason: The person sees what is new at a glance; a dot keeps the rule that titles and
selectors show no counters.
