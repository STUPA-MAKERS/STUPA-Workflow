---
id: "000597"
title: A section in a detail and a small tile show one ghost row
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/src/app/features/apply/status-timeline.component.html
  - frontend/src/app/features/gremien/attendance-detail/attendance-detail.component.html
  - frontend/src/app/features/todos/linked-list/todo-linked-list.component.html
  - frontend/src/app/pages/applications/applications-detail.component.html
  - frontend/src/app/pages/applications/attachments-panel.component.html
  - frontend/src/app/pages/tickets/ticket-detail.component.html
  - frontend/src/app/pages/expenses/booking-detail/booking-detail.component.html
  - frontend/src/app/pages/expenses/booking-form/booking-form.component.html
  - frontend/src/app/pages/invoices/invoice-detail/invoice-detail.component.html
  - frontend/src/app/pages/budget/budget-dashboard.component.html
  - frontend/src/app/pages/admin/cd-variants/cd-variants.component.html
  - frontend/src/app/pages/admin/webhooks/webhooks.component.html
  - frontend/src/app/pages/admin/flow/transition-detail.component.html
  - frontend/src/app/pages/admin/flow/transition-lists.component.html
  - frontend/src/app/pages/admin/forms/form-editor.component.html
  - frontend/src/app/pages/admin/version-history/version-history.component.html
  - frontend/src/app/pages/dashboard/dashboard.component.html
  - frontend/src/app/features/meetings/meetings-list/meetings-list.component.html
  - frontend/src/app/features/meetings/calendar-subscribe/calendar-subscribe.component.html
scope:
  - frontend/src/app/
---

# A section in a detail and a small tile show one ghost row

An empty list must show one ghost row (`rows="1"`) when it is a section of a detail or a small
tile. All other empty lists keep their ghost rows (000205, 000412).

- Section of a detail: a section head with an action, and the empty list below it. Examples:
  Antrag "Anhänge" and "Verlauf", "Unterbuchungen", Rechnung "Buchungen", the Kostenstelle
  lists, "Verknüpft" and the linked to-dos (000582), Ticket "Duplikat", webhook deliveries, the
  actions and transitions of the flow editor, an empty form group, the version history and the
  attendance of one meeting.
- Small tile: Start "Heute", "Meine Anträge" and "Aufgaben", "Keine kommenden Sitzungen" and
  the calendar subscription in the account.
- Unchanged: dialogs, sheets and pickers keep their rows, so the dialog height does not jump
  while the user types. Main lists and tabs keep 3 or 5 rows, because they fill the page. The
  chat and the protocol text keep their own shapes.

Reason: A detail has many sections and a tile is small. One row says "empty" and keeps the
detail and the start page short.

Test: Review of the `rows` input of each `app-empty-state` in the files above.
