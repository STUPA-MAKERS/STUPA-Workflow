---
id: "001622"
title: A changed approved amount can be higher than the requested amount
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A changed approved amount can be higher than the requested amount

A change of the approved amount (001620) must allow an amount higher than the requested amount.
The amount must not be negative. The dialog must show a warning when the new amount is higher
than the requested amount. This exception applies only to 001620. A first approval (001610)
must still not be higher than the requested amount.

Reason: Extra costs after the approval are the main case for a change, and they can make the amount higher than the requested amount.

Test: A backend unit test changes the amount to a value above the requested amount.
