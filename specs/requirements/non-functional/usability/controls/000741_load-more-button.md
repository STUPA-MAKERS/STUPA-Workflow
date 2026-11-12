---
id: "000741"
title: A button that loads more rows of a list is centred with a chevron
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/shared/load-more.styles.spec.ts:loadMoreButtons"
implementation:
  - frontend/src/app/features/calendar/calendar.component.html
  - frontend/src/app/features/meetings/meetings-list/meetings-list.component.html
scope:
  - frontend/src/app/features
---

# A button that loads more rows of a list is centred with a chevron

A button that loads more rows of a list must be a text button in the centre of the list. Its
icon must be a chevron that points to the side where the new rows appear: up for a button
above the rows, down for a button below the rows. This includes "Frühere Tage laden" and
"Spätere Tage laden" of the Kalender and "Frühere Sitzungen laden" of the Sitzungen.

Reason: Two buttons with the same job that look different read as two different functions.

Test: `frontend/src/app/shared/load-more.styles.spec.ts` reads the templates of both lists and
fails when a load button has another icon or leaves the centre.
