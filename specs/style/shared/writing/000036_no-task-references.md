---
id: "000036"
title: Texts do not refer to old tasks
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/
  - frontend/
  - mcp/
  - typst/
  - deploy/
  - .claude/
  - specs/
---

# Texts do not refer to old tasks

Code, comments, docstrings, skills, docs, CI files and deploy files must not refer to old
tasks, issues, pull requests, spec sections or decision codes. State the rule itself.
References to RFCs, OpenID, DSGVO, a product ticket number such as `T-0042` and a spec rule
with `§` are allowed.

Reason: An old reference means nothing to the next reader and goes stale.
