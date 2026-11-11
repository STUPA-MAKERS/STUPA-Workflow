---
id: "000731"
title: The public calendar page shows the public entries
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
  - frontend/src/app/pages
---

# The public calendar page shows the public entries

The page `/public-calendar` must be open without a sign-in. It must show the public Termine
(§F/meetings/calendar/000730) and the public meetings (§F/meetings/calendar/000732) and no other
kind of entry: no cards, no events, no external calendars.

The page must have the views of the calendar tab: the month grid and the week view on a desktop
(§F/meetings/calendar/000728), the list of days on a phone (§F/meetings/calendar/000726), and the
search (§F/meetings/calendar/000727). It must have the filter by Gremium and no other filter. A
press on an entry must open its public fields in a dialog, or in a bottom sheet on a phone. The
page must have no button that creates a Termin.

The start page of a person who is not signed in must have the choice `Kalender` that opens this
page.

Reason: A person without an account must see when the Gremien meet and which public dates
exist.

Test: A frontend unit test renders the start page without a session and finds the link to
`/public-calendar`. A backend unit test reads the public entries without a session and finds no
card and no external entry.
