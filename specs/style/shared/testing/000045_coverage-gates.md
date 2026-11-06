---
id: "000045"
title: Coverage gates hold
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/pyproject.toml
  - frontend/jest.config.js
  - .github/workflows/ci.yml
scope:
  - backend/
  - frontend/
---

# Coverage gates hold

The backend must keep at least 97 % line and branch coverage. The frontend must keep at least
98 % statements, 96 % branches, 98 % functions and 99 % lines.

Test: `fail_under` in `backend/pyproject.toml`, `coverageThreshold` in `frontend/jest.config.js`.
