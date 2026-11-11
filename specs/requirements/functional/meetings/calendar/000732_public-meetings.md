---
id: "000732"
title: The public calendar shows the meetings of Gremien with public protocols
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - backend/app/modules/meetings
  - frontend/src/app/features
---

# The public calendar shows the meetings of Gremien with public protocols

The public calendar must show each meeting of a Gremium that has `protocols_public`. A public
meeting must show only its title, its date, its start time, its end time and the name of its
Gremium. It must never show the agenda, the attendance, the votes, the live state or a link into
the meeting. A meeting of a Gremium without `protocols_public` must never be public.

No other public page must list meetings. Guest participation by QR must create no public list.

Reason: A Gremium that publishes its protocols meets in public, so the date of its meeting is
public too. The content of a meeting stays internal until its protocol is final.

Test: A backend unit test reads the public entries without a session, finds the meeting of a
Gremium with `protocols_public` with exactly these fields, and does not find the meeting of a
Gremium without it.
