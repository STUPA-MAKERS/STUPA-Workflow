---
id: "000843"
title: A text that the database cannot store answers 422
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/shared/test_error_contract.py:test_a_text_that_the_database_refuses_is_a_422"
implementation:
  - backend/app/shared/errors.py
scope:
  - backend/app/shared
---

# A text that the database cannot store answers 422

A request with a text that the database refuses must answer 422 `validation_error` as
`application/problem+json`: a text with a NUL character (SQLSTATE 22021) and a JSON value
with a NUL escape (SQLSTATE 22P05). Each other error of the database must stay a 500
`internal_error`.

Reason: Such a text is an error of the input and not of the server. A 500 tells the person
nothing and raises an alarm for a request that a client can repeat at will.

Test: The unit test gives the error handler each of the two SQLSTATE values and a
different one, and reads the status and the code.
