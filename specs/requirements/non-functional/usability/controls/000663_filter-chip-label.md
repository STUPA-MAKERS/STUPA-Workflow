---
id: "000663"
title: A filter chip shows its name, then name and value
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/vendor/ui-kit/src/lib/filter-select/filter-select.component.spec.ts:FilterSelectComponent"
  - "frontend/src/app/pages/tickets/tickets.component.spec.ts:TicketsComponent"
  - "frontend/src/app/features/meetings/meetings-timeline.service.spec.ts:MeetingsTimelineService"
implementation:
  - frontend/vendor/ui-kit/src/lib/filter-select
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
  - frontend/src/app/pages/admin/oauth-grants
  - frontend/src/app/pages/admin/audit
  - frontend/src/app/pages/admin/translations
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A filter chip shows its name, then name and value

A filter chip without a choice must show only the name of the filter ("Status"). A filter chip
with a choice must show the name, a colon and the value ("Status: Offen"). A chip must not
show a word for "all" ("Alle Gremien", "Aktion: Alle Aktionen") and must not show a verb
("Anzeigen: …").

The board chip of the boards page is not a filter and keeps its text.

Reason: The pages use five patterns. The person learns one pattern and reads from the chip
alone if a filter is set.

Test: A unit test of the kit filter select expects the name alone without a value and
"name: value" with a value. A unit test of each page with chips expects no chip text that
starts with "Alle" or holds "Anzeigen".
