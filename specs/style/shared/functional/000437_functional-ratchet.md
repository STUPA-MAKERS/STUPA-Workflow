---
id: "000437"
title: A CI ratchet keeps the functional style from getting worse
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - scripts/check_functional.py
  - scripts/functional-baseline/
  - .github/workflows/ci.yml
scope:
  - backend/
  - frontend/
  - frontend/vendor/ui-kit
  - mcp/
  - typst/
  - .github/workflows
---

# A CI ratchet keeps the functional style from getting worse

A script must count the violations of the functional style rules against a stored baseline. CI
must fail when the count goes up. A change that lowers the count must also lower the baseline.
