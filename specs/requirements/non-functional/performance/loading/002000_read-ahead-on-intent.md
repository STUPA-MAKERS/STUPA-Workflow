---
id: "002000"
title: A list reads the details of a row ahead only on a sign of intent
kind: non-functional
status: approved
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

A list must read all the details of a row ahead only on a sign of intent (ui-kit:002289).
Without such a sign, a list must read ahead only the first read of its top five rows. A read
ahead must be quiet and must not run more than four reads at a time.

Reason: A list of 30 rows with 9 reads each sent 270 requests on each open. They stood in the
queue of the server before the reads of the click and slowed down every person.

Test: The test of `prefetchDetails` reads that only the first read of the top five rows runs,
that a sign of intent starts all reads of that row, and that a fresh row reads nothing again.
