---
id: "000044"
title: A change comes with its tests
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/tests/
  - frontend/src/
  - mcp/antragsplattform_mcp/tests
scope:
  - backend/tests/
  - frontend/src/
  - mcp/antragsplattform_mcp/tests
---

# A change comes with its tests

A change must come with the tests of its rule in the same pull request. The author must write
the code and its tests first and must then let CI run them (000048). A test must not use
`skip` or `xfail` without a written reason.
