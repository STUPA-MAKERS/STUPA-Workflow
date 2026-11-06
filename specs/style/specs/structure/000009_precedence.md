---
id: "000009"
title: A spec wins over other guidance
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - specs/
---

# A spec wins over other guidance

A rule in `specs/` must win over a skill, a memory file and a code comment. If code and a spec
disagree, an agent must tell the owner. It must not change the code or the spec silently.

Reason: Only one source can be binding. Otherwise two agents follow two different rules.
