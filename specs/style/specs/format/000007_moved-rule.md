---
id: "000007"
title: A moved rule keeps its number
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - specs/
scope:
  - specs/
---

# A moved rule keeps its number

If a file moves to a different folder, the path part of its ID changes. The number and the file
name must not change. Every reference must change in the same pull request.
