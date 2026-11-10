---
id: "000582"
title: An empty "Verknüpft" section shows an empty state
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/features/todos/card-detail/todo-card-detail.component.spec.ts:TodoCardDetailComponent"
  - "frontend/src/app/features/todos/linked-list/todo-linked-list.component.spec.ts:TodoLinkedListComponent"
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.html
  - frontend/src/app/features/todos/linked-list/todo-linked-list.component.html
scope:
  - frontend/src/app/features/todos
---

# An empty "Verknüpft" section shows an empty state

When a "Verknüpft" section shows with no row, it must show `app-empty-state` with ghost rows
of the row shape (000205, 000412). This applies to the card detail of every card type and to
the linked to-dos of a vote, an invoice, a booking and a cost centre.

- Card detail: the heading is "Nichts verknüpft", with one ghost row.
- Linked to-dos: the heading is "Keine To-Dos verknüpft", unless the page sets its own heading,
  with three ghost rows like the other lists of the page.

The section action ("Verknüpfen", the link and plus buttons) stays in the section head. The
empty state has no action of its own, because the head already has one. A user without write
access sees no empty section, because the section does not show.

Reason: A heading with only blank space below it looks like a load that did not finish. One
ghost row keeps the card short, because the card has many sections.

Test: Unit tests render the card detail and the linked list with write access and no link, and
expect the empty state with its heading.
