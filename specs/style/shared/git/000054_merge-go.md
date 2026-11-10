---
id: "000054"
title: A merge needs the go of the owner
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - .
scope:
  - .
---

# A merge needs the go of the owner

An agent must merge a pull request only after the owner says so. The owner can give a standing
go for one kind of pull request. After the go, the agent must wait until every required check
(000628) is green. When a required check fails for a cause outside the pull request, the agent
must tell the owner. It must then merge only when the owner gives a go for that pull request
with the red check named.

Reason: A merge with a red check hides the next real failure of that check.
