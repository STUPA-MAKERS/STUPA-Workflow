---
id: "001364"
title: The icon of an empty state names what is missing
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.spec.ts:EmptyStateComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.ts
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The icon of an empty state names what is missing

The small icon before the hint of an empty state (001360) is the `icon` input of
`app-empty-state`. Every empty state must set it for its context:

- A search or a filter without a hit shows the crossed-out lens (`searchOff`). When the same
  empty state serves an empty list and a list with a set filter, the icon must follow whether a
  search or a filter is set.
- An empty list without a search or a filter shows the icon of its section in the navigation,
  for example the calendar for the calendar, the file for the Anträge and the receipt for the
  Rechnungen.
- An empty section, tile or dialog list shows the icon of the thing that is missing, for
  example the paper clip for attachments, the clock with the arrow for a history and the bell
  for notifications.

The crossed-out lens must not show where nobody searched or filtered.

Reason: A lens on every empty state says "nothing found" where the person did not search. The
icon of the missing thing says at once what would be there.

Test: A unit test renders the empty state with an icon and expects that icon before the hint.
