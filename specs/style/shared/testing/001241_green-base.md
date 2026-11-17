---
id: "001241"
title: The base of a change is the newest green CI run before it
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "backend/tests/unit/scripts/test_ci_scope.py:test_base_is_the_green_run_with_the_smallest_diff"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_no_ancestor_runs_every_part"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_unreadable_api_runs_every_part"
implementation:
  - scripts/ci_scope.py
scope:
  - .github/workflows/ci.yml
---

# The base of a change is the newest green CI run before it

The base must be the commit of a green CI run that is an ancestor of the tested commit. A pull
request must take the green runs of its own branch and the green pushes to its target branch. A
push must take the green pushes to its branch. Of these commits, the base must be the one with
the fewest changed files. When no such run exists or the GitHub API cannot be read, every part
must run.

Reason: A part can be skipped only when an earlier run proved it green. A cancelled or red run
proves nothing, so the base goes back to the last green run.

Test: `backend/tests/unit/scripts/test_ci_scope.py`.
