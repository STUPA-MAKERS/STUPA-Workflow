---
id: "001302"
title: The activity page shows a running meeting above the list
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/activity/activity.component.html
scope:
  - frontend/src/app/pages/activity
---

# The activity page shows a running meeting above the list

While a meeting that the person can see is live, the activity page must show the live card of
that meeting above the list, one card for each live meeting. The card is the live card of the
old start page: date block, title, Gremium, the status "Live" and the link into the meeting.
Without a live meeting the page must not show the card or an empty place for it.

Reason: The start page is the fastest way into a running vote.
