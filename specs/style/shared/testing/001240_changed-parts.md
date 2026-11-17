---
id: "001240"
title: CI runs only the jobs of the changed parts
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "backend/tests/unit/scripts/test_ci_scope.py:test_spec_change_runs_no_part"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_frontend_change_runs_frontend_and_stack"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_write_sets_outputs"
implementation:
  - scripts/ci_scope.py
  - .github/workflows/ci.yml
scope:
  - .github/workflows/ci.yml
---

# CI runs only the jobs of the changed parts

The CI must run the jobs of a part of the repository only when a file of the part changed since
the base (001241). The job `specs` must run on every change. A change of rule specs only must run
no other check job.

Reason: A full run takes about 20 minutes, and a change of one spec or of the frontend waited
for the backend suites.

Test: `backend/tests/unit/scripts/test_ci_scope.py`, and the job summary of `detect` lists the parts that run.
