---
id: "001271"
title: An item belongs to a person when they made, hold or touched it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
implementation: null
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# An item belongs to a person when they made, hold or touched it

An item must count as an item of the person in these cases:

- An Antrag: the person is the applicant, captured it on behalf of an applicant, observes it,
  or wrote a comment on it.
- A to-do card: the person created it, is an assignee, wrote a comment on it, or a comment
  mentions the person.
- A ticket: the person reported it, is the assignee, wrote a note on it, or a note mentions the
  person.
- A meeting: the person created it, is its protokollant, or is on its attendance list.

A membership in a Gremium alone must not make an item an item of the person. Buchungen and
invoices are not items of the activity page.

Reason: The page shows what concerns the person, not everything the person can read.
