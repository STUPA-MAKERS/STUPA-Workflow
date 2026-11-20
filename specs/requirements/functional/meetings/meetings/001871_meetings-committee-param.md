---
id: "001871"
title: The meeting list reads the Gremium filter from the URL
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/meetings/meetings.component.spec.ts:MeetingsComponent"
  - "frontend/src/app/features/meetings/meetings-list/meetings-list.component.spec.ts:MeetingsListComponent"
  - "frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.spec.ts:GremiumDetailComponent"
implementation:
  - frontend/src/app/features/meetings/meetings.component.ts
  - frontend/src/app/features/meetings/meetings-list/meetings-list.component.ts
  - frontend/src/app/features/meetings/meetings-timeline.service.ts
  - frontend/src/app/features/gremien/gremium-meetings/gremium-meetings.component.html
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
scope:
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
---

# The meeting list reads the Gremium filter from the URL

`/meetings?committee=<id>` must open the meeting list with the Gremium chip set to that
Gremium. A pick in the Gremium chip must write `committee` into the URL, and "Alle Gremien"
must remove it. An id that the chip does not offer must drop, and the list must show every
meeting. "In „Sitzungen“ öffnen" on the tab "Sitzungen" of a Gremium and the same item in the
⋮ menu of the Gremium must open `/meetings?committee=<id>`. The chips "Zeitraum" and
"Protokoll" of the tab must not go into the link, because the meeting list has no such filter.

Reason: The link opened every meeting of every Gremium, so the person had to pick the Gremium
again in the chip.

Test: the meeting specs open the list with `?committee=` and check the request, the URL after
a pick and the drop of an unknown id. The Gremium specs check the link.
