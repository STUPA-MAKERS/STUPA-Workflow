---
id: "000048"
title: CI runs the full suites
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/
---

# CI runs the full suites

Before a push, an agent must run only lint, the type check and at most one fast test file. CI
runs the full suites, the integration tests and the coverage gates. A failure must be read from
the log of the failed job.
