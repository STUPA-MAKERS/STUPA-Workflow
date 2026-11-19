---
id: "001280"
title: The Gremien list shows its skeleton until the logos have loaded
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/gremien/gremien-page/gremien.component.spec.ts:GremienComponent"
  - "frontend/src/app/shared/util/preload-images.spec.ts:preloadImages"
implementation:
  - frontend/src/app/features/gremien/gremien-page/gremien.component.ts
  - frontend/src/app/shared/util/preload-images.ts
scope:
  - frontend/src/app/features/gremien/gremien-page/
  - frontend/src/app/shared/util/preload-images.ts
---

# The Gremien list shows its skeleton until the logos have loaded

On the first load, the Gremien list must show its skeleton until each Gremium logo of the
answer has loaded or failed. The wait must not be longer than 3 seconds. After 3 seconds the
rows show, and a logo that is still loading appears in its row when it arrives. A logo that
fails counts as loaded, because its row shows the initials. A refresh (pull to refresh) must
not show the skeleton again.

Reason: Without the wait, the rows show with initials and the logos replace them one by one,
so the list flickers. The limit stops one slow logo from holding the whole list.

Test: A unit test of the list checks that the skeleton stays until the preload is done and
that a list without a logo does not wait. A unit test of the preloader checks that a failed
image counts as done and that the wait ends after 3 seconds.
