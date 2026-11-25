---
id: "003035"
title: The statuses of an element are a list in the admin configuration
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
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
of element must have a status list that an admin edits under Verwaltung, each list on its own page (003040): the list of the
Bestellungen on the page `Bestellphasen` (`/admin/order-phases`, permission
`admin.order_phases`, `Bestellphasen verwalten`) and the list of the Events on the page
`Veranstaltungsphasen` (`/admin/event-phases`, permission `admin.event_phases`,
`Veranstaltungsphasen verwalten`). Each status of a list must have a key, a name in each UI language, a
color, a position and a phase (003036). The key must be unique in its list and must not change
after the create. Exactly one status of a list must be the start status of a new element, and
its phase must be `open`. Each list must have at least one status of each phase. Each change of a
list must write an audit entry and a config revision that an admin can restore.

Reason: Each student government works in its own steps, and the platform is the same for each.
One page per list says on its name which element it configures, and one permission per page
follows the other pages of Verwaltung.
A key that does not change keeps the stored elements, the flow settings and the webhooks valid
when an admin renames a status.

Test: A backend unit test adds, renames and reorders a status, gets 422 for a start status that
is not `open` and for a list without a `void` status, and reads the audit entry.
