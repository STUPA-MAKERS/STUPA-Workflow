---
id: "001300"
title: The activity page is the start page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-22
implementation:
  - frontend/src/app/app.routes.ts
  - frontend/src/app/core/auth/home-redirect.guard.ts
  - frontend/src/app/layout/nav.service.ts
  - frontend/src/app/core/features/feature.service.ts
scope:
  - frontend/src/app/app.routes.ts
  - frontend/src/app/core/auth
  - frontend/src/app/layout
  - frontend/src/app/pages/activity
---

# The activity page is the start page

The page "Aktivität" at `/activity` (001270) must be the start page of a signed-in person.
After the sign-in, on `/` and on `/login` the app must lead a signed-in person to `/activity`.
`/dashboard` must lead to `/activity` too. The navigation must not have an entry "Start". The
entry "Aktivität" must be the first entry of the rail and of the phone bar.

While the feature `Aktivität` is off (000756), `/applications` must take the place of
`/activity` in each of these cases, and the link of the mark in the rail and of the 403 page
must lead there too.

Reason: The work list of the old start page is the page "Aufgaben", and the activity shows what
happened to the items of the person. Old links and bookmarks to `/dashboard` keep working. The Anträge are the core of the platform
and have no switch, so they are always there.
