---
name: flow-engine-bug-fixes
description: "2026-06-10 hardening — flow engine + project-wide bug fixes, typing/lint/tests zeroed; all merged to main (5b5f8fd)"
metadata: 
  node_type: memory
  type: project
---

All merged + pushed to main (2b31dcd flow engine, c54cf2a project-wide races, 5b5f8fd typing/tests/lint). Branch `fix/flow-engine-bugs` in the `.claude/worktrees/mobile-view` worktree tracks main; `worktree-mobile-view` branch untouched.

Flow engine (2b31dcd): manual fire of vote branch transitions → 409; compare-guard op/type drift fails closed (was 500); `_guard_fires_on_deadline` negation polarity + deterministic order; extras dispatcher per-action try/except; self-loops + branch-on-non-vote rejected at save; leaf guard value shapes validated; flow deadlines always cleared on state change + marker rows; `deadline_passed` derived from DB on manual paths (`bool|None` param, worker passes True).

Project-wide (c54cf2a): applications concurrent PATCH → 409 not 500; voting cast/close serialized via vote row lock; gremium membership unknown principal → 404; deadline worker marker committed atomically with fire; webhook SSRF log redacted; frontend seq-guards on applications list/detail fetches; flow-editor save double-click guard.

Quality bars (5b5f8fd): basedpyright 0 errors repo-wide (run with `--pythonpath backend/venv/bin/python`; venv lives at `backend/venv` in MAIN repo, not worktree); ruff clean; backend 1329 + frontend 563 tests green; tsc + eslint clean. Test fakes pattern: when service code grows new session calls (execute/scalar/get), the per-file fakes need matching stubs — that's what the 8 "pre-existing" failures were.

Known design gap (open): no outbox — crash between flow-fire commit and action dispatch drops actions.
