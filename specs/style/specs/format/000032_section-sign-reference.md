---
id: "000032"
title: Code refers to a rule with the § sign
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - specs/
scope:
  - specs/
---

# Code refers to a rule with the § sign

A docstring or a code comment must refer to a rule with `§` and the full rule ID, without a
space, for example `§F/meetings/voting/000024`. A spec, a commit message or a pull request text
must refer to a rule without `§`.

Reason: The `§` sign makes a reference easy to find with one search in the code.

Test: `scripts/check_specs.py`: every `§` reference in the code names a spec file that exists.
