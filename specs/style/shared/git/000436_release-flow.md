---
id: "000436"
title: A release goes from development to main by pull request
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - .
scope:
  - .
---

# A release goes from development to main by pull request

A release must follow these steps:

1. A feature release is a pull request from `development` into `main` with release notes, the
   migration list and the deploy steps. The owner merges it.
2. A hotfix is a pull request into `main`. The owner merges it.
3. The owner tags `main` and publishes the release.
4. Sync `main` back into `development` with a merge commit.
