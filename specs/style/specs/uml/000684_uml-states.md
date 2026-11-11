---
id: "000684"
title: A state view is written by hand and has the states of its check constraint
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - specs/
  - scripts/
  - backend/app/modules
---

# A state view is written by hand and has the states of its check constraint

The code changes a status in many functions, so a script cannot find the transitions. A state
view is therefore written by hand, one file `specs/uml/states/<table>-<column>.json` for each
status column with a life cycle. The life cycles are at least: `meeting-status`,
`meeting_guest-status`, `vote-status`, `protocol-status` and `backup-status`.

A state view must have `table` and `column`, one element for each state with `initial: true` on
the first state, and one edge for each transition. The edge must have `trigger`, the action that
causes the transition in a few words, and `path`, the file that makes the change.

When the column has a check constraint that lists its values, `scripts/build_uml.py --check`
must fail if the states of the view are not exactly these values. A change that adds or removes
a value must change the view in the same commit.

Reason: The life cycles are the part of the model that a reader needs most and that the tables
show least. The check keeps the hand-written states equal to the database.

Test: `scripts/build_uml.py --check` in the CI job `specs`.
