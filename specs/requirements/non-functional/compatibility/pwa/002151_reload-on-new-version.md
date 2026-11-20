---
id: "002151"
title: A new app version reloads the app at once
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/core/pwa/app-version.service.spec.ts:AppVersionService"
implementation:
  - frontend/src/app/core/pwa/app-version.service.ts
  - frontend/src/app/core/pwa/app-version.interceptor.ts
  - frontend/src/app/app.config.ts
scope:
  - frontend/src/app/
---

# A new app version reloads the app at once

When an API answer carries an `X-App-Version` (002150) that is not the build ID of the
running app, the app must load the new version through the service worker and reload the
page at once. The app must not show an update notice. While a text field has the focus,
the reload must wait until the next page change or the next API answer while no text field
has the focus. An answer without the header or a local build with the build ID `dev` must not
reload.

Reason: An old frontend against a new API can fail. A notice that waits for a click leaves
people on the old version for days. Typed text that is not saved must not be lost.

Test: A unit test answers with another version and expects the service worker update and
one reload. With the focus in a text field it expects no reload until the next page change.
