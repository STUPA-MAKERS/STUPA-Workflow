---
id: "002858"
title: A new Bestellung needs an approved Antrag
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
  - backend/app/modules/applications
---

# A new Bestellung needs an approved Antrag

The server must create a Bestellung only for an Antrag in a state with the flag approved
(F/applications/flow/000571). It must answer 409 `application_not_approved` for an Antrag in a
different state. A Bestellung that exists must stay and must stay editable when the Antrag
leaves the approved state.

Reason: Before the approval there is no money to spend. A purchase before the decision can stay
without cover.

Test: A backend integration test refuses a Bestellung for a submitted Antrag, creates one for an
approved Antrag and edits it after the Antrag left the state.
