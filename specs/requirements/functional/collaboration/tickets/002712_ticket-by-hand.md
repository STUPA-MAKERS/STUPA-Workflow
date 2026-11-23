---
id: "002712"
title: The team creates a ticket by hand
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The team creates a ticket by hand

A person with the work right in a Bereich must be able to create a ticket there for an account
or for an e-mail address. For an address the Bereich must have a Postfach, and the first public
message must go out as a mail (002733).

Reason: A case often starts with a call or a talk, and the team must be able to write to a
person first.

Test: A unit test creates a ticket for an address in a Bereich without a Postfach and expects
422.
