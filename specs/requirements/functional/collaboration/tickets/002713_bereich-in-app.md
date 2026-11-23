---
id: "002713"
title: A Bereich can take tickets from signed-in persons
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A Bereich can take tickets from signed-in persons

A Bereich must have the switch `In der App erreichbar`. While the switch is on, a signed-in
person must be able to choose the Bereich in the ticket dialog of the help menu. A person
without a session must reach only the Bereich `Plattform` (000150).

Reason: A member asks a Gremium a question without a mail. A public form for each Bereich would
open each team to spam.

Test: A unit test sends a ticket without a session to a Bereich with the switch on and expects
403.
