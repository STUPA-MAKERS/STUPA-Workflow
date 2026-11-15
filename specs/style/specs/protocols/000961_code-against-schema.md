---
id: "000961"
title: A test checks the output of the code against the schema
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/tests/_support/protocols.py
scope:
  - specs/
  - backend/tests
---

# A test checks the output of the code against the schema

A protocol spec of a JSON format with `implementation` must list at least one test in `tests`.
The test must build the format with the code of the platform and must validate the result
against the schema file with `tests._support.protocols.assert_matches_schema`. A test of a format
that the platform reads must validate its input fixture the same way.

Reason: The schema is the contract, and the code is a second copy of it. Only a test that runs
the code finds the drift between the two.

Test: Review. Every test in `tests` names the spec with `§` (000223).
