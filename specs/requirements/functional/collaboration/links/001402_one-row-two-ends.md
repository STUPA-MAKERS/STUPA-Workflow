---
id: "001402"
title: A link is one row with two typed ends
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/todos/models.py
  - backend/migrations/versions/c4d1e2f3a5b6_link_any_to_any.py
scope:
  - backend/app/modules/todos
---

# A link is one row with two typed ends

The table `link` must store each link once, with the columns `a_kind`, `a_id`, `b_kind`, `b_id`,
`created_by` and `created_at`. The ends must be in a fixed order (`(a_kind, a_id)` sorts before
`(b_kind, b_id)`), and a unique index on the four columns must hold. A check constraint must
allow only the kinds of F/collaboration/links/001400. The deletion of an element must delete its
links in the same transaction, through a database trigger on the table of each kind.

Reason: One generic row keeps the model the same for every pair of kinds. A link with eleven
kinds on each end would need 22 foreign key columns. The fixed order prevents a second row for
the same pair in the other direction. The trigger does the work of `ON DELETE CASCADE`, which a
column without a foreign key does not have.

Test: A backend integration test deletes an invoice and checks that its links are gone. A unit
test inserts the same pair in both directions and gets one row.
