---
id: "000947"
title: The objection to a circular vote is a button
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - frontend/src/app/features/voting/vote-cast.component.ts
scope:
  - frontend/src/app/features/voting
---

# The objection to a circular vote is a button

The view of an open circular vote must show the action "Widersprechen" as a button for each
eligible member (000915). The button must not be in a menu. A press must ask for a
confirmation that says that the objection ends the vote for all members.

Reason: The objection is a right of each member from the Satzung. An action in a menu is not
found.

Test: A frontend unit test finds the button in the view of an open circular vote and finds the
confirmation after a press.
