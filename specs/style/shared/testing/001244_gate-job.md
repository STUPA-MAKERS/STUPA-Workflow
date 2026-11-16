---
id: "001244"
title: One gate job sums up the CI run
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - .github/workflows/ci.yml
scope:
  - .github/workflows/ci.yml
---

# One gate job sums up the CI run

The job `ci-ok` must need every other job of `ci.yml` and must run always. It must fail when a
job failed or was cancelled, and when `detect` is not green. A skipped job must count as green.

Reason: GitHub counts a skipped job as green. When `detect` fails, every job after it is skipped,
and only the gate job can turn the run red.

Test: The job `ci-ok` in `.github/workflows/ci.yml`.
