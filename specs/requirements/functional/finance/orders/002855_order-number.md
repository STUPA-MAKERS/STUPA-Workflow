---
id: "002855"
title: A new Bestellung gets a random number of eight characters
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
---

# A new Bestellung gets a random number of eight characters

A new Bestellung must get a number of the form `B-` and eight random characters, made like the
number of a ticket (F/collaboration/tickets/002714). The number must be unique and must not
change.

Reason: People name a Bestellung in a mail or in a meeting. A number is shorter than a title and
does not show how many Bestellungen exist.

Test: A backend unit test creates two Bestellungen and checks the form and the difference of the
numbers.
