---
id: "000032"
title: Code refers to a rule with the § sign
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - specs/
---

# Code refers to a rule with the § sign

A docstring or a code comment refers to a rule with `§` and the full rule ID, for example
`§F/meetings/voting/000024`. A spec, a commit message or a pull request text refers to a rule
without `§`.

Reason: The `§` sign makes a reference easy to find with one search in the code.

Test: Every `§` reference in the code names a spec file that exists.
