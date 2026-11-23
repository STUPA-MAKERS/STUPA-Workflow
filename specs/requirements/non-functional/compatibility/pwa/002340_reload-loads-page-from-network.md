---
id: "002340"
title: The reload to a new app version loads the page from the network
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/core/pwa/app-version.service.spec.ts:AppVersionService"
  - "frontend/src/app/core/pwa/ngsw-navigation.spec.ts:navigationRequestStrategy"
implementation:
  - frontend/src/app/core/pwa/app-version.service.ts
  - frontend/ngsw-config.json
scope:
  - frontend/src/app/core/pwa
  - frontend/ngsw-config.json
---

# The reload to a new app version loads the page from the network

The service worker must load a page from the network first and use its stored page only
when the network fails (`navigationRequestStrategy: "freshness"`). The reload of
ui-kit:002151 must start at once and must not wait for a download of the service worker.
When the next answer after that reload still carries the same server version, the app must
remove the service worker and reload one more time.

Reason: The new `index.html` names the new files, and the network serves every file that
the service worker does not hold yet. A reload that waits for the download of the service
worker shows the old version when the download is slow, or when iOS stops the service
worker in the background. The second reload covers a service worker that still runs an
older config.

Test: A unit test answers with another version and expects one reload without a service
worker update. An answer with the same version after one reload expects the removal of the
service worker and a second reload. A config test expects the strategy `freshness`.
