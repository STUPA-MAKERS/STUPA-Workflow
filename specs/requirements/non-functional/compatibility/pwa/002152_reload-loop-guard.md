---
id: "002152"
title: The app reloads only once for the same server version
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/core/pwa/app-version.service.spec.ts:AppVersionService"
implementation:
  - frontend/src/app/core/pwa/app-version.service.ts
scope:
  - frontend/src/app/
---

# The app reloads only once for the same server version

Before a reload of 002151, the app must store the server version and the time in the session
storage of the tab. When an answer reports the same server version within 10 minutes after
that reload, the app must not reload again.

Reason: A broken service worker cache or a proxy cache can keep the old frontend after the
reload. Without the guard, the app would reload without end.

Test: A unit test stores a reload for one version, answers with that version and expects no
reload. An answer with a third version reloads.
