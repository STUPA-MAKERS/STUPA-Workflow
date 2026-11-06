---
id: "000018"
title: The rule text uses must and must not
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# The rule text uses must and must not

Use `must` for an obligation and `must not` for a prohibition. Use the present tense for a fact
that the rule depends on.

Test: `scripts/check_specs.py` finds a draft or approved rule without `must`.
