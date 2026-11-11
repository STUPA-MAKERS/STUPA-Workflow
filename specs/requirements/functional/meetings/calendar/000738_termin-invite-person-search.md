---
id: "000738"
title: The invitation search finds each active account by name
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The invitation search finds each active account by name

The dialog of a Termin must find the persons to invite with a search over the names of all
active accounts. The search must start at two characters and must show the name only, never the
e-mail address. A person must be able to invite each account that the search finds.

Reason: A Termin with a person outside the own Gremien is the usual case. The name of an
account is known in the house, the address is not.

Test: A backend unit test searches with two characters as a person without a Gremium, finds an
account of another Gremium and finds no address in the answer.
