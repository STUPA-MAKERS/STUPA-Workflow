---
id: "003035"
title: The statuses of an element are a list in the admin configuration
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - backend/app/modules/statuses/models.py
  - frontend/src/app/pages/admin/statuses/statuses.component.ts
scope:
  - backend/app/modules/statuses
  - backend/app/modules/orders
  - frontend/src/app/pages/admin
---

# The statuses of an element are a list in the admin configuration

The statuses of a Bestellung and of an Event must not be fixed in the code. Each of these kinds
of element must have a status list that an admin edits under Verwaltung, each list on its own
page (003040): the list of the Bestellungen on the page `Bestellzustände` (`/admin/order-
statuses`, permission `admin.order_statuses`, `Bestellzustände verwalten`) and the list of the
Events on the page `Veranstaltungszustände` (`/admin/event-statuses`, permission
`admin.event_statuses`, `Veranstaltungszustände verwalten`). Each status of a list must have a
key, a name in each UI language, a color and a kind (003036). The statuses must not have a
sequence: no status follows another, and an element can go from each status to each other
status. The list keeps the order in which the statuses were added, and the dropdowns show them
in this order. The key must be unique in its list and must not change after the create. Exactly
one status of a list must be the start status of a new element, and its kind must be `open`.
Each list must have at least one status of each kind. Each change of a list must write an audit
entry and a config revision that an admin can restore.

Reason: Each student government works with its own statuses, and the platform is the same for
each. A status says where an element is, not which step comes next, so the statuses need no
sequence. One page per list says on its name which element it configures, and one permission per
page follows the other pages of Verwaltung. A key that does not change keeps the stored
elements, the flow settings and the webhooks valid when an admin renames a status.

Test: A backend unit test adds and renames a status, gets 422 for a start status that is not
`open` and for a list without a `void` status, and reads the audit entry.
