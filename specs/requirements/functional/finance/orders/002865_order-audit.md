---
id: "002865"
title: Each write of a Bestellung has an audit entry
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - backend/app/modules/audit
---

# Each write of a Bestellung has an audit entry

The create, the change, the status change and the delete of a Bestellung must each write an
audit entry with the old and the new values. The audit revert must work for a change and for a
status change. It must not work for a delete.

Reason: A Bestellung leads to a booking, so each change must be traceable. A delete is not
revertable anywhere on the platform (F/administration/admin/000163).

Test: A backend integration test changes the price, reverts the audit entry and reads the old
price.
