---
id: "002000"
title: A list reads the details of a row ahead only on a sign of intent
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/core/cache/detail-prefetch.spec.ts:prefetchDetails"
implementation:
  - frontend/src/app/core/cache/detail-prefetch.ts
scope:
  - frontend/src/app/core/cache
---

# A list reads the details of a row ahead only on a sign of intent

A list must read all the details of a row ahead only when the pointer of a mouse moves onto the
link of the row, when a finger, pen or mouse presses it, or when it gets the focus. Without such
a sign, a list must read ahead only the first read of its top five rows. A read ahead must be
quiet and must not run more than four reads at a time.

Reason: A list of 30 rows with 9 reads each sent 270 requests on each open. They stood in the
queue of the server before the reads of the click and slowed down every person. A press comes
about 100 ms before the click, so the detail still opens from the cache.

Test: The test of `prefetchDetails` reads that only the first read of the top five rows runs,
that a press, the focus or a mouse over a link starts all reads of that row, that a touch over
a link starts none, and that a fresh row reads nothing again.
