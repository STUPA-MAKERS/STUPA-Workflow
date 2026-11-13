---
id: "000847"
title: A read after a write does not stand on a read from before it
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/core/cache/cache.interceptor.spec.ts:cacheInterceptor"
implementation:
  - frontend/src/app/core/cache/cache.interceptor.ts
  - frontend/src/app/core/cache/http-cache.service.ts
scope:
  - frontend/src/app/core/cache
---

# A read after a write does not stand on a read from before it

A cached read that the browser starts after a write must send its own request. It must not
join a read that started before the write, and the answer of such a read must not go into
the cache.

Reason: The server can answer a read before it takes the write. A page that reads a list
again after its save would then show the state before the save, for example a switch in the
state that the save just changed.

Test: The test of the cache interceptor starts a read, a write and a second read, reads two
requests and reads that the answer of the first read is not the stored one.
