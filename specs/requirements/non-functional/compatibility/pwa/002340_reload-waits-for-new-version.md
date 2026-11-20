---
id: "002340"
title: The reload to a new app version shows the new version
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/core/pwa/app-version.service.spec.ts:AppVersionService"
implementation:
  - frontend/src/app/core/pwa/app-version.service.ts
scope:
  - frontend/src/app/core/pwa
---

# The reload to a new app version shows the new version

The reload of ui-kit:002151 must start only after the service worker has downloaded the new
version, and the page must then use that version. When the service worker finds no newer
version, fails, or takes longer than 60 seconds, the app must remove the service worker
before the reload, so that the reload loads the app from the network. When the service
worker reports a ready new version after an answer with another server version, the app must
reload, also within the time of ui-kit:002152.

Reason: The service worker fetches the changed files one after the other. On a phone this
can take longer than a few seconds. A reload before the end of the download shows the old
version again, and the loop guard then holds the next reload, so only a restart of the app
showed the new version.

Test: A unit test holds the download and expects no reload until it ends. A failed or slow
download and a service worker without a newer version expect the removal and one reload. A
ready version after a held reload expects a reload.
