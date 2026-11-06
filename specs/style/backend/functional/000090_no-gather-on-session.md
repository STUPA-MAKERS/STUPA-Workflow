---
id: "000090"
title: One AsyncSession is never used concurrently
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/
  - backend/worker/
  - mcp/
  - typst/typst_service/
---

# One AsyncSession is never used concurrently

Calls on one `AsyncSession` must run one after the other. Code must not use `asyncio.gather`
over one session. It must use a list comprehension with `await`, not a generator expression
with `await`.

Reason: The session is not safe for concurrent use, and the error shows only under load.
