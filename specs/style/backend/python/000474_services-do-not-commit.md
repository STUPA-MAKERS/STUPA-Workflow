---
id: "000474"
title: Service functions do not commit
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules
---

# Service functions do not commit

A service function must not commit. The router or the worker must own the transaction.

Reason: A caller can then put several service calls into one transaction.
