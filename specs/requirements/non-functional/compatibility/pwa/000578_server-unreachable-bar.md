---
id: "000578"
title: The offline bar shows when the server is unreachable
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
tests:
  - "frontend/src/app/core/api/server-reachability.service.spec.ts:ServerReachabilityService"
implementation:
  - frontend/src/app/core/api/server-reachability.service.ts
  - frontend/src/app/core/api/reachability.interceptor.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The offline bar shows when the server is unreachable

When an API request gets no answer or the answer 502, 503 or 504, the app must request
`GET /api/health` at once. When that request fails too, the app must show the offline bar of
000222, also while the browser has network. In this state the bar must say "Server nicht
erreichbar".

While the bar shows, the app must request `GET /api/health` every 5 seconds. After the first
answer 200, the app must remove the bar.

Reason: During a deploy, the API container restarts and the reverse proxy answers 502 or 503.
The browser still has network, so `navigator.onLine` stays true and the offline bar did not
show. The first health request is necessary because one route can answer 503 for its own
reason, for example the backups page without a recipient.

Test: A unit test answers one request with 502 and the health request with 503, expects the
bar with "Server nicht erreichbar", answers the next health request with 200 and expects the
bar to go.
