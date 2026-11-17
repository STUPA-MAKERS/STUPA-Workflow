---
id: "001242"
title: Main, a manual run and a change of the CI run every job
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
tests:
  - "backend/tests/unit/scripts/test_ci_scope.py:test_main_and_dispatch_run_every_part"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_global_file_runs_every_part"
implementation:
  - scripts/ci_scope.py
scope:
  - .github/workflows/ci.yml
---

# Main, a manual run and a change of the CI run every job

A push to `main`, a pull request into `main` and a manual run must run every part. A change of
`.github/`, `scripts/ci_scope.py`, `flake.nix`, `flake.lock` or `.gitmodules` must run every
part.

Reason: A release is tested in full once. A change of the CI or of the tool versions can break
every part, and the table of 001243 cannot see it.

Test: `backend/tests/unit/scripts/test_ci_scope.py`.
