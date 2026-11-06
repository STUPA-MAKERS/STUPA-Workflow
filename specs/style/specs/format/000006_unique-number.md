---
id: "000006"
title: The number is the identity of a rule
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# The number is the identity of a rule

The number must be unique over all specs. The number is the real ID. Kind and path only make
the ID readable and easy to find. A new rule gets the highest number in `specs/` plus one. A
number is never used again. A rule that is not in force keeps its file with `status: removed`.

Reason: An old reference must not point to a different rule, also after a file moves.

Test: `scripts/check_specs.py`: no number occurs in two file names.
