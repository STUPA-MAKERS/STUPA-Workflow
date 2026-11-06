---
id: "000036"
title: Texts do not refer to old tasks
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
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
tasks, issues or pull requests. They must not refer to spec sections or decision codes. They
must state the rule itself. References to RFCs, OpenID, DSGVO, a product ticket number such as
`T-0042` and a spec rule with `§` are allowed.

Reason: An old reference means nothing to the next reader and goes stale.
