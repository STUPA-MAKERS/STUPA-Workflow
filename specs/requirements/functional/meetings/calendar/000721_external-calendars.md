---
id: "000721"
title: An admin subscribes an external calendar
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/pages/admin
---

# An admin subscribes an external calendar

The admin page `Kalender` with the permission `admin.calendars` must manage the external
calendars. An external calendar must have a name, an `https` URL of an ICS feed and a scope:
all persons, or one Gremium. The entries of a calendar for all must be readable by each signed-in
person. The entries of a calendar of a Gremium must be readable by the persons who read the
meetings of that Gremium.

Reason: The dates of the university and of the Gremien live in other systems. One subscription
by an admin replaces a subscription by each person.

Test: A backend unit test reads an entry of a Gremium calendar as a non-member and does not find
it.
