---
id: "000732"
title: The public calendar shows the meetings of Gremien with public protocols
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/public.py
  - frontend/src/app/features/calendar/public-entry/public-entry.component.html
scope:
  - backend/app/modules/calendar
  - backend/app/modules/meetings
  - frontend/src/app/features
---

# The public calendar shows the meetings of Gremien with public protocols

The public calendar must show each meeting of a Gremium that has `protocols_public`. A public
meeting must show its title, its date, its start time, its end time, the name of its Gremium and
the titles of its TOPs that are not internal (§F/public/public-pages/000172). A past meeting
must also show a link to its public protocol when that protocol is public
(§F/public/public-pages/000171). A public meeting must never show an internal TOP, the text or
the attachments of a TOP, the attendance, the votes, the live state or a link into the meeting.
A meeting of a Gremium without `protocols_public` must never be public.

No other public page must list meetings. Guest participation by QR must create no public list.

Reason: A Gremium that publishes its protocols meets in public, so the date of its meeting is
public too. The content of a meeting stays internal until its protocol is final.

Test: A backend unit test reads the public entries without a session, finds the meeting of a
Gremium with `protocols_public` with these fields and without its internal TOP, and does not find the meeting of a
Gremium without it.
