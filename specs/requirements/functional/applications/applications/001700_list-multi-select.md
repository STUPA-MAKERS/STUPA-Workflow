---
id: "001700"
title: The Antrag list has a multiple selection
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The Antrag list has a multiple selection

A person with the permission `application.manage` must be able to select more than one Antrag
in the Antrag list. A selection bar must show the actions `Übergang auslösen`
(`Fire transition`) and `Mitteilung senden` (`Send message`). One action must take at most 100
Anträge.

Reason: Prod data holds 12 equal comments and 14 equal status changes on 2026-11-10. One person did the same step on each Antrag of a round.

Test: A frontend unit test selects rows and checks the selection bar.
