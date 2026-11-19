---
id: "001600"
title: A vote state takes a decision made outside the platform
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# A vote state takes a decision made outside the platform

A person with the permission `application.record_decision` must be able to record a decision on
an Antrag in a vote state when the Gremium decided in a meeting without a vote on the platform.
The dialog `Beschluss erfassen` (`Record decision`) must ask for:

- the result: `Angenommen` (`Passed`) or `Abgelehnt` (`Failed`),
- the date of the meeting, not later than today,
- the Gremium, preset with the Gremium of the vote state (000243).

The dialog must also offer, as optional fields, the counts of yes, no and abstain votes and a
link to a meeting or a protocol of the platform. The result must fire the `pass` or the `fail`
transition of the vote state (000233) with all of its actions and mails, and it must write a
`status_change` audit entry with `outsideDecision: true`.

Reason: Prod data holds 7 forced approvals from vote states, all 4 cases in `Gremium der Kostenstelle`. The Gremium decided in a meeting, and the flow had no way to record this decision.

Test: A backend integration test records a passed and a failed decision and checks the new state, the mails and the audit entry.
