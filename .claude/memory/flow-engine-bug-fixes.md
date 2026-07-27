---
name: flow-engine-bug-fixes
description: "2026-06-10 hardening: flow engine and project-wide bug fixes, typing, lint and tests at zero, all merged to main (5b5f8fd)"
metadata: 
  node_type: memory
  type: project
---

All work is merged and pushed to main (2b31dcd flow engine, c54cf2a project-wide races, 5b5f8fd
typing, tests and lint). The branch `fix/flow-engine-bugs` in the `.claude/worktrees/mobile-view`
worktree tracks main. The `worktree-mobile-view` branch stays untouched.

Flow engine (2b31dcd): a manual fire of a vote-branch transition now gives 409. An operator or type
drift in a compare guard fails closed, where it gave 500 before. `_guard_fires_on_deadline` got the
negation polarity right and a deterministic order. The extras dispatcher wraps each action in its
own try/except. Save now rejects a self-loop and a branch on a non-vote state. The engine validates
the leaf guard value shapes. A state change always clears the flow deadlines and the marker rows.
`deadline_passed` comes from the DB on the manual paths (a `bool|None` parameter, and the worker
passes True).

Project-wide (c54cf2a): a concurrent PATCH on an application gives 409, not 500. A vote row lock
serializes cast and close. A gremium membership call with an unknown principal gives 404. The
deadline worker commits the marker atomically with the fire. The webhook SSRF log is redacted. The
frontend guards the applications list and detail fetches with a sequence number. The flow editor
guards save against a double click.

Quality bars (5b5f8fd): basedpyright reports 0 errors repo-wide. Run it with
`--pythonpath backend/venv/bin/python`. The venv lives at `backend/venv` in the MAIN repo, not in
the worktree. ruff is clean. Backend 1329 and frontend 563 tests are green. tsc and eslint are
clean. Test fakes pattern: when service code grows new session calls (execute, scalar, get), the
per-file fakes need matching stubs. That gap caused the 8 "pre-existing" failures.

Known design gap (open): there is no outbox. A crash between the flow-fire commit and the action
dispatch drops the actions.
