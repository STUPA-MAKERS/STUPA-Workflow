---
id: "000717"
title: A Termin invites Gremien and persons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# A Termin invites Gremien and persons

A Termin can invite any number of Gremien and persons. An invited Gremium must stand for the
persons who read the meetings of that Gremium at the time of the read, not at the time of the
invitation. The creator must be able to invite only a Gremium whose meetings the creator reads,
or any Gremium with `calendar.manage`.

Reason: A Gremium changes its members. A new member must see the open Termine of the Gremium.

Test: A backend unit test adds a member to an invited Gremium and reads the Termin as that
member.
