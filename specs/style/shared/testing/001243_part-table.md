---
id: "001243"
title: A part also runs for a change of a file that it reads
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/scripts/test_ci_scope.py:test_backend_change_runs_mcp_too"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_backend_test_change_does_not_run_mcp"
  - "backend/tests/unit/scripts/test_ci_scope.py:test_a_read_file_runs_its_part"
implementation:
  - scripts/ci_scope.py
scope:
  - scripts/ci_scope.py
  - backend/tests
  - frontend/src
  - mcp/
---

# A part also runs for a change of a file that it reads

The table `PARTS` in `scripts/ci_scope.py` must list for each part its own folder and every
file outside it that its tests or checks read. A test that starts to read a file of another part
must add the file to the table in the same change. These parts are in the table:

| Part | Jobs | Reads also |
| --- | --- | --- |
| backend | be-lint, be-typecheck, be-unit, be-integration, be-contract, be-migrations, coverage-gate | scripts/, deploy/, Dockerfiles, specs/protocols/, specs/uml/, the UI text catalog, typst/vendor/ |
| frontend | fe-unit | the functional baseline |
| stack | axe, e2e | backend/, frontend/, deploy/, scripts/e2e.sh |
| mcp | mcp | backend/app/ |
| typst | typst | |
| admin_cli | admin-cli | |
| compose | compose | |
| functional | functional | all code, no spec |

Reason: A part that reads a file of another part breaks when that file changes, for example the
route parity test of the MCP server (001200) when a backend route changes.

Test: `backend/tests/unit/scripts/test_ci_scope.py`.
