---
id: "000014"
title: A change goes through a pull request
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - specs/
scope:
  - specs/
---

# A change goes through a pull request

A change to a spec must follow these steps:

1. Find the topic folder. If there is none, make it. 2. Copy the template and give the rule its
number (000006). 3. Set `status: draft` and set `updated` to the current date. 4. Update the
index with `python3 scripts/check_specs.py --write`. 5. Open a pull request. The owner sets
`approved`. 6. Before the merge, bring the branch up to `development` and run the check again,
so that a number that `development` took in the meantime shows.
