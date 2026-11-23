---
id: "002743"
title: A change of a Postfach is in the audit log
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# A change of a Postfach is in the audit log

Each create, change and delete of a Postfach and each change of its switch must write an audit
entry with the person and the changed fields. The entry must not hold a password.

Reason: The Postfach decides where the mails of a team go, so a change must be traceable
(000291).

Test: A unit test changes the password and expects an entry that names the field and not the
value.
