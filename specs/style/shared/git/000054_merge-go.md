---
id: "000054"
title: A merge needs the go of the owner
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - .
scope:
  - .
---

# A merge needs the go of the owner

An agent must merge a pull request only after the owner says so. After the go, it must wait for
green CI. While CI is known to be broken, it must merge at once after the go.
