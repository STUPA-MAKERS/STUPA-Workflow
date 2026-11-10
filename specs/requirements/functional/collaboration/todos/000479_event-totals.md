---
id: "000479"
title: An Event shows the totals of its links
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/todos/events.py
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/budget
  - backend/app/modules/applications
---

# An Event shows the totals of its links

An Event must show these totals of its linked Anträge and Buchungen: requested amount,
approved amount, expenses, income and balance. The totals must count all linked elements,
because each reader of the Event can read them.

Reason: The Gremium sees the money of an Event in one place, across Kostenstellen and fiscal
years.

Test: A backend unit test computes the totals for a board reader without `budget.read`.
