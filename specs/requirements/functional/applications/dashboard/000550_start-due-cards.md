---
id: "000550"
title: Start shows the due cards of the person
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - frontend/src/app/pages/dashboard
  - backend/app/modules/todos
---

# Start shows the due cards of the person

The side sheet `Heute` of the start page must show the cards that are assigned to the person
and are due within 7 days or overdue. It must show at most 5 cards, on the phone at most 3, the
oldest due date first. Each row must link to its card. The heading of the block must not show a
count (spec 000560). The sheet must not show the block when no card is due.

Reason: The rail counts the open cards, and the start page must show the urgent ones.

Test: A frontend unit test shows an overdue card first and hides the block without due cards.
