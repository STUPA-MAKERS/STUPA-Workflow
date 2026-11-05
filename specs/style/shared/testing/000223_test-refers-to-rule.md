---
id: "000223"
title: A test refers back to its rule
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/tests
  - frontend/src/app
  - mcp/antragsplattform_mcp/tests
---

# A test refers back to its rule

A unit test that a spec lists in `tests` must name the rule in its docstring. Use `§` and the
full rule ID, for example `§F/meetings/voting/000024`.

Reason: The reader of a test sees which rule it protects. A search finds the link in both
directions.

Test: Every `tests` entry names a test function that exists, and its docstring has the `§`
reference to the spec.
