---
id: "002901"
title: Delegations of planned meetings get the voting right
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/migrations/versions/b7e3d1a9c460_delegation_always_votes.py
scope:
  - backend/app/modules/delegations
  - backend/migrations
---

# Delegations of planned meetings get the voting right

The migration of 002900 must set `delegate_voting` to true on every delegation of a meeting with
the status `planned`. It must not change a delegation of a live or closed meeting.

Reason: A planned meeting must follow 002900. A held meeting is history, and its counts must not
change.

Test: Review of the migration.
