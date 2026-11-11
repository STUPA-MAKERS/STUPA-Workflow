---
id: "000733"
title: The public calendar has an ICS feed without a token
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# The public calendar has an ICS feed without a token

The route `/api/public/calendar.ics` must give the entries of the public calendar as an ICS feed
without a sign-in and without a token. The feed must hold the same entries and the same fields
as the public calendar page, with no organiser and no attendee. The public calendar page must
have the button `Kalender abonnieren` that shows the URL of the feed with a copy button.

The route must have the rate limit of the public routes, and the server must cache the feed for
5 minutes.

Reason: A person without an account must be able to subscribe the public dates in a calendar
app. A cache keeps the load of a feed that many apps fetch low.

Test: A backend unit test fetches the feed without a session, finds a public Termin and a public
meeting, and finds no `ORGANIZER` and no `ATTENDEE` line.
