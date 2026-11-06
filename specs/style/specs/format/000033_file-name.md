---
id: "000033"
title: The file name is number and name
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - scripts/check_specs.py
scope:
  - specs/
---

# The file name is number and name

The file name must have the form `<number>_<name>.md`:

- `<number>` is the six-digit number of the rule.
- `<name>` is a short name of the rule in lower case, with `-` between the words.

Example: `000024_every-vote-is-secret.md`.

Test: `scripts/check_specs.py`: the file name matches `^[0-9]{6}_[a-z0-9]+(-[a-z0-9]+)*\.md$`.
