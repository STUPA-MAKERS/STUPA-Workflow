---
id: "000578"
title: The offline bar shows when the server is unreachable
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/pwa/src/offline.service.ts
  - frontend/src/app/core/
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The offline bar shows when the server is unreachable

When an API request gets no answer or the answer 502, 503 or 504, the app must show the
offline bar of 000222, also while the browser has network. In this state the bar must say
"Server nicht erreichbar".

While the bar shows, the app must request `GET /api/health` every 5 seconds. After the first
answer 200, the app must remove the bar.

Reason: During a deploy, the API container restarts and the reverse proxy answers 502 or 503.
The browser still has network, so `navigator.onLine` stays true and the offline bar did not
show.

Test: A unit test answers one request with 502, expects the bar with "Server nicht
erreichbar", answers the health request with 200 and expects the bar to go.
