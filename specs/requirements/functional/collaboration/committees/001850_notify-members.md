---
id: "001850"
title: A Gremium notifies its members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# A Gremium notifies its members

The detail page of a Gremium must show the action "Mitglieder benachrichtigen" to a holder of
`members.notify` in that Gremium, and to nobody else. The action must open a dialog with a
subject and a message. A send must deliver one mail to each recipient of 001852.

Reason: The managers of a Gremium need one way to reach all members without a mailing list
outside the platform.

Test: A frontend test that the action shows only with `members.notify`, and a backend test that
a send delivers one mail to each member.
