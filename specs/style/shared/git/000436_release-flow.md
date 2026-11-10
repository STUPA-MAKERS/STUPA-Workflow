---
id: "000436"
title: A release goes from development to main by pull request
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - .
scope:
  - .
---

# A release goes from development to main by pull request

A release must follow these steps:

1. A feature release is a pull request from `development` into `main` with release notes, the
   migration list and the deploy steps.
2. A hotfix is a pull request into `main`.
3. The owner merges the pull request. An agent must merge it only with a go of the owner. The
   go can be a standing go for release pull requests (000054).
4. The owner tags `main` and publishes the release (000053).
5. Sync `main` back into `development` with a merge commit.
