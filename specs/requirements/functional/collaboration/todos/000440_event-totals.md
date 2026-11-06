---
id: "000440"
title: An Event shows the totals of its links
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/budget
  - backend/app/modules/applications
---

# An Event shows the totals of its links

An Event must show these totals of its linked Anträge and Buchungen: requested amount,
approved amount, expenses, income and balance. The totals must count only the elements that
the viewer can read. The totals must show the number of linked elements that they do not
count.

Reason: The Gremium sees the money of an Event in one place, across Kostenstellen and fiscal
years. A total must not show a sum that the viewer cannot read item by item.

Test: A backend unit test computes the totals for a viewer without `budget.read`.
