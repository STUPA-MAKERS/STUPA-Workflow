---
id: "002714"
title: A new ticket gets a random number of eight characters
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_service.py:test_a_used_number_is_drawn_again"
  - "backend/tests/unit/modules/tickets/test_ticket_service.py:test_a_drawn_number_has_eight_characters_of_the_alphabet"
implementation:
  - backend/app/modules/tickets/numbers.py
  - backend/app/modules/tickets/service.py
  - backend/migrations/versions/c7a94e12d5b3_ticket_random_numbers.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A new ticket gets a random number of eight characters

A new ticket must get a number of the form `T-7K3QX9MD`: `T-` and eight random characters from
the digits `2` to `9` and the capital letters without `I`, `L` and `O`. The characters must come
from a cryptographic random source. The number must be unique on the platform: when a draw
gives a number that a ticket has, the platform must draw again. A move to a different Bereich
must not change the number.

Reason: A number in sequence shows how many tickets the platform gets and lets a person guess
the number of a different ticket. The number is the reference in the subject of a mail
(002734), so it must point to one ticket for all time. The left-out characters look like `0`
and `1`.

Test: A unit test lets the random source give a used number first and expects a different
number on the ticket. A second test checks the form of 1000 numbers.
