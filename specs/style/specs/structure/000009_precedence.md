---
id: "000009"
title: A spec wins over other guidance
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - specs/
---

# A spec wins over other guidance

A rule in `specs/` wins over a skill, a memory file and a code comment. If code and a spec
disagree, tell the owner. Do not change the code or the spec silently.

Reason: Only one source can be binding. Otherwise two agents follow two different rules.
