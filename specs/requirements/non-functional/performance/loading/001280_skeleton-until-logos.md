---
id: "001280"
title: The Gremien list shows its skeleton until the logos have loaded
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
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

The Gremien list must give the Gremium logos as the images of its rows (ui-kit:002288).

Reason: The logos are the images that make the Gremien list flicker.

Test: A unit test of the list checks that a list without a logo does not wait.
