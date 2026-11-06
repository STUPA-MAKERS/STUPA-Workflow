---
id: "000044"
title: Tests come first
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/tests/
  - frontend/src/
  - mcp/antragsplattform_mcp/tests
---

# Tests come first

A change must start with a failing test, then the minimal code, then the clean-up. A test must
not use `skip` or `xfail` without a written reason.
