---
id: "000033"
title: The file name is number and name
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - specs/
---

# The file name is number and name

The file name has the form `<number>_<name>.md`:

- `<number>` is the six-digit number of the rule.
- `<name>` is a short name of the rule in lower case, with `-` between the words.

Example: `000024_every-vote-is-secret.md`.

Test: The file name matches `^[0-9]{6}_[a-z0-9]+(-[a-z0-9]+)*\.md$`.
