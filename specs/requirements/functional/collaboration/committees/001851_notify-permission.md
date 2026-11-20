---
id: "001851"
title: Only members.notify sends a message to the members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/app/modules/gremien_overview
  - backend/app/modules/auth
  - frontend/src/app/features/gremien
  - frontend/src/app/pages/admin
---

# Only members.notify sends a message to the members

Only a holder of the Gremium permission `members.notify` in that Gremium must be able to send a
message to its members. The forced roles `vorstand` and `manager` must have `members.notify` by
default, and a migration must add it to these roles in every existing Gremium. The role
`member` must not have it by default. A global role must not grant it (000267). The OAuth scope
`committees:write` must cap it. The role editor must show it as "Mitglieder benachrichtigen".

Reason: A mail to all members is a message in the name of the Gremium. A separate permission
lets a Gremium give the right to other roles, for example a Schriftführung.

Test: A backend test that a `manager` sends, a `member` gets 403 and an admin without a
membership gets 403.
