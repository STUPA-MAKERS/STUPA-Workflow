---
id: "000476"
title: Test doubles of Principal model the admin bypass
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/tests
---

# Test doubles of Principal model the admin bypass

A fake `Principal` in a test must apply the scope cap and the admin bypass like
`Principal.has`.

Reason: Else a test passes for a permission check that fails in production.
