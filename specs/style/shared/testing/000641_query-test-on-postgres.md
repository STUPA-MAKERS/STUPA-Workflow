---
id: "000641"
title: A test of a database query runs on Postgres
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/tests/integration
  - .claude/skills/conventions/SKILL.md
scope:
  - backend/tests
---

# A test of a database query runs on Postgres

A new test of code that builds a database query must be an integration test on a real Postgres.
It must not give the result of the query through a fake session.

Reason: A fake session returns the rows that the test wrote down, in call order. A wrong `WHERE`
then passes, and a change of the query order that changes no behaviour fails.
