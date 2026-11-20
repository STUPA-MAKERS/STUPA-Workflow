---
id: "001892"
title: Every filter chip has the one chip look
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/calendar/calendar.component.spec.ts:CalendarComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/filter-select
  - frontend/src/app/features/calendar
  - frontend/src/app/pages/todos/todos.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every filter chip has the one chip look

A filter chip must have the look of the kit chip (`.chip`): 32px high, the radius `md`, a
thin edge and 13.5px text. This applies on every page, on the phone and on the desktop, also
beside a search pill of size `md`. A page must not give a filter chip its own height, radius,
edge or padding. The size `md` of `app-filter-select` must be used only for a select in a
field row, never for a filter.

Reason: The Kalender showed its filters as 44px round pills, the to-do filter on the phone
was 36px high, and all other pages show 32px chips. The person sees one control with one job
in three looks.

Test: A unit test of the Kalender expects filter chips and no chip of size `md`.
Screenshots of the Kalender, Graph and Aufgaben filter rows in light, dark and very high
contrast, on the desktop and the phone, show chips of the same height and radius.
