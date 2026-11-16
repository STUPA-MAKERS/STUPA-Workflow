---
id: "000006"
title: The number is the identity of a rule
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# The number is the identity of a rule

The number must be unique over all specs. The number is the real ID. Kind and path only make
the ID readable and easy to find. A new rule gets the highest number plus one, counted over `development` and every open pull
request. When two pull requests hold the same number, the pull request that merges later must
give its specs new numbers before its merge. A number is never used again. A rule that is not in force keeps its file with `status: removed`.

Reason: An old reference must not point to a different rule, also after a file moves.

Test: `scripts/check_specs.py`: no number occurs in two file names, and no spec of a branch has
a number that `origin/development` gave to a different spec after the branch left it.
