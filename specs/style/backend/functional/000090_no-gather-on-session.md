---
id: "000090"
title: One AsyncSession is never used concurrently
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - backend/worker/
  - mcp/
  - typst/typst_service/
---

# One AsyncSession is never used concurrently

Await calls on one `AsyncSession` one after the other. Do not use `asyncio.gather` over one
session. Use a list comprehension with `await`, not a generator expression with `await`.

Reason: The session is not safe for concurrent use, and the error shows only under load.
