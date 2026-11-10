---
id: "000045"
title: Coverage gates hold
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/pyproject.toml
  - frontend/jest.config.js
  - .github/workflows/ci.yml
scope:
  - backend/
  - frontend/
---

# Coverage gates hold

The backend must keep at least 97 % line and branch coverage. The unit tests and the
integration tests of the backend count together for this value. The frontend must keep at least
98 % statements, 96 % branches, 98 % functions and 99 % lines.

Reason: When only the unit tests count, each change must reach the value with fakes, and a test
on the real database adds nothing to the gate.

Test: The CI job `coverage-gate` with `fail_under` in `backend/pyproject.toml`, and
`coverageThreshold` in `frontend/jest.config.js`.
