---
id: "002341"
title: The app checks the version when the page comes back
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/core/pwa/app-version.service.spec.ts:AppVersionService"
implementation:
  - frontend/src/app/core/pwa/app-version.service.ts
scope:
  - frontend/src/app/core/pwa
---

# The app checks the version when the page comes back

When the page comes back to the user (the tab or the installed app is visible again, the
browser restores it from the back-forward cache, or the device is online again), the app
must send one read to `/api/health` and must take its `X-App-Version` (002150) like every
other API answer. A local build with the build ID `dev` must not send it.

Reason: A live page, such as a meeting or a board, talks over a WebSocket and can go a long
time without an HTTP answer. Without the read, it notices a new version only at the next
page change.

Test: A unit test signals a return of the page, answers the read with another version and
expects one reload.
